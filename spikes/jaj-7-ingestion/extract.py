"""Spike JAJ-7: extrae un grafo de arquitectura desde un repo FastAPI usando solo el AST de Python.

Uso:
    python extract.py <ruta-al-repo> [-o salida.json]

No ejecuta ni importa el código analizado: solo lo parsea.
Detecta endpoints (con prefijos de include_router/mount), y por cada uno los accesos a DB,
caché, servicios externos y tareas en segundo plano alcanzables por el grafo de llamadas,
con archivo:línea. Marca patrones de riesgo (N+1, HTTP sin timeout, llamadas bloqueantes en async).
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options", "api_route", "websocket"}
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "tests", "test", "migrations", "alembic", "docs"}

DB_READ = {"exec", "execute", "query", "get", "scalar", "scalars", "fetch", "fetchrow", "fetchval", "refresh", "first", "one", "all"}
DB_WRITE = {"add", "add_all", "delete", "commit", "flush", "merge", "bulk_save_objects", "bulk_insert_mappings", "executemany", "rollback"}
DB_RECEIVER_HINTS = ("session", "db", "conn", "connection", "cursor", "engine", "transaction", "tx")
DB_TYPES = {"Session", "AsyncSession", "Connection", "Pool", "AsyncConnection", "scoped_session"}
CACHE_HINTS = ("redis", "cache", "memcache")
CACHE_METHODS = {"get", "set", "setex", "delete", "hget", "hset", "incr", "expire", "mget", "mset", "lpush", "rpush", "publish"}
HTTP_LIBS = {"requests", "httpx", "aiohttp", "urllib3"}
HTTP_CALLS = {"get", "post", "put", "patch", "delete", "request", "head", "send", "stream"}
SDK_LIBS = {"boto3", "botocore", "slack_sdk", "slack_bolt", "stripe", "openai", "anthropic", "smtplib",
            "jira", "atlassian", "pdpyras", "googleapiclient", "google", "zoomus", "msal", "sendgrid", "twilio"}


@dataclass
class Effect:
    kind: str  # db | cache | http | sdk | background
    op: str
    detail: str
    file: str
    line: int
    in_loop: bool = False
    awaited: bool = True


@dataclass
class FuncInfo:
    fid: str
    module: "Module"
    node: ast.FunctionDef | ast.AsyncFunctionDef
    cls: str | None = None
    effects: list[Effect] = field(default_factory=list)
    calls: list[tuple[str, int, bool]] = field(default_factory=list)  # (fid, line, in_loop)
    unresolved: int = 0


@dataclass
class Module:
    name: str
    path: Path
    rel: str
    tree: ast.Module
    imports: dict[str, str] = field(default_factory=dict)  # alias -> dotted target
    funcs: dict[str, ast.AST] = field(default_factory=dict)
    classes: dict[str, ast.ClassDef] = field(default_factory=dict)
    assigns: dict[str, ast.AST] = field(default_factory=dict)  # module-level name -> value


class Project:
    def __init__(self, root: Path):
        self.root = root
        self.modules: dict[str, Module] = {}
        self.funcs: dict[str, FuncInfo] = {}
        self.parse_errors: list[str] = []
        self._suffix_cache: dict[str, str | None] = {}

    # ---------- carga ----------
    def load(self) -> None:
        for path in sorted(self.root.rglob("*.py")):
            rel_parts = path.relative_to(self.root).parts
            if any(p in SKIP_DIRS or p.startswith(".") for p in rel_parts[:-1]):
                continue
            if path.name.startswith("test_") or path.name == "conftest.py":
                continue
            src = path.read_text(encoding="utf-8", errors="replace")
            try:
                tree = ast.parse(src, filename=str(path))
            except SyntaxError as e:
                # PEP 758 (Python 3.14): `except A, B:` sin paréntesis. Se reescribe para el parser local.
                fixed = re.sub(r"^(\s*except\s+)([\w.]+(?:\s*,\s*[\w.]+)+)(\s*(?:as\s+\w+)?\s*:)", r"\1(\2)\3", src, flags=re.M)
                try:
                    tree = ast.parse(fixed, filename=str(path))
                    self.parse_errors.append(f"{path}: reescrito ({e.msg})")
                except SyntaxError as e2:
                    self.parse_errors.append(f"{path}: {e2}")
                    continue
            parts = list(rel_parts)
            parts[-1] = parts[-1][:-3]
            if parts[-1] == "__init__":
                parts = parts[:-1]
            name = ".".join(parts) or "__root__"
            mod = Module(name=name, path=path, rel=str(path.relative_to(self.root)), tree=tree)
            self.modules[name] = mod
        for mod in self.modules.values():
            self._index(mod)
        self._load_sql_queries()

    def _load_sql_queries(self) -> None:
        """Lee queries nombradas de aiosql (`-- name: x`) para saber si son lectura o escritura y qué tabla tocan."""
        self.sql_queries: dict[str, tuple[str, str]] = {}
        for path in self.root.rglob("*.sql"):
            if any(p in SKIP_DIRS for p in path.relative_to(self.root).parts):
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for m in re.finditer(r"--\s*name:\s*([\w-]+)[^\n]*\n(.*?)(?=--\s*name:|\Z)", text, flags=re.S):
                name = m.group(1).rstrip("!<>*#^$").replace("-", "_")
                body = re.sub(r"--[^\n]*", "", m.group(2)).strip()
                verb = body.split(None, 1)[0].upper() if body else ""
                if verb == "WITH":
                    verb = next((v for v in ("INSERT", "UPDATE", "DELETE") if v in body.upper()), "SELECT")
                tbl = re.search(r"\b(?:FROM|INTO|UPDATE)\s+([\w.]+)", body, flags=re.I)
                op = "write" if verb in ("INSERT", "UPDATE", "DELETE") else "read"
                self.sql_queries[name] = (op, tbl.group(1) if tbl else "")

    def _index(self, mod: Module) -> None:
        is_pkg = mod.path.name == "__init__.py"
        pkg = mod.name if is_pkg else mod.name.rpartition(".")[0]
        for node in mod.tree.body:
            if isinstance(node, ast.Import):
                for a in node.names:
                    mod.imports[a.asname or a.name.split(".")[0]] = a.name if a.asname else a.name.split(".")[0]
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ""
                if node.level:
                    up = pkg.split(".") if pkg else []
                    up = up[: len(up) - (node.level - 1)] if node.level > 1 else up
                    base = ".".join([*up, base] if base else up)
                for a in node.names:
                    mod.imports[a.asname or a.name] = f"{base}.{a.name}" if base else a.name
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                mod.funcs[node.name] = node
                self._add_func(mod, node, None)
            elif isinstance(node, ast.ClassDef):
                mod.classes[node.name] = node
                for sub in node.body:
                    if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        self._add_func(mod, sub, node.name)
            elif isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        mod.assigns[t.id] = node.value
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
                mod.assigns[node.target.id] = node.value
            elif isinstance(node, ast.TypeAlias):  # py3.12 `type X = ...`
                mod.assigns[node.name.id] = node.value

    def _add_func(self, mod: Module, node, cls: str | None) -> None:
        fid = f"{mod.name}:{cls + '.' if cls else ''}{node.name}"
        self.funcs[fid] = FuncInfo(fid=fid, module=mod, node=node, cls=cls)

    # ---------- resolución de nombres ----------
    def find_module(self, dotted: str) -> str | None:
        if dotted in self.modules:
            return dotted
        if dotted in self._suffix_cache:
            return self._suffix_cache[dotted]
        hits = [m for m in self.modules if m.endswith("." + dotted)]
        res = min(hits, key=len) if hits else None
        self._suffix_cache[dotted] = res
        return res

    def resolve_symbol(self, mod: Module, name: str, depth: int = 0) -> tuple[str, str] | None:
        """Devuelve ("module", modname) | ("func", fid) | ("class", "mod:Cls") | ("assign", "mod:name")."""
        if depth > 6:
            return None
        if name in mod.funcs:
            return ("func", f"{mod.name}:{name}")
        if name in mod.classes:
            return ("class", f"{mod.name}:{name}")
        if name in mod.assigns:
            return ("assign", f"{mod.name}:{name}")
        target = mod.imports.get(name)
        if not target:
            return None
        m = self.find_module(target)
        if m:
            return ("module", m)
        owner, _, sym = target.rpartition(".")
        om = self.find_module(owner) if owner else None
        if om:
            return self.resolve_symbol(self.modules[om], sym, depth + 1)
        return None

    def resolve_expr(self, mod: Module, expr: ast.AST) -> tuple[str, str] | None:
        if isinstance(expr, ast.Name):
            return self.resolve_symbol(mod, expr.id)
        if isinstance(expr, ast.Attribute):
            base = self.resolve_expr(mod, expr.value)
            if base and base[0] == "module":
                return self.resolve_symbol(self.modules[base[1]], expr.attr)
            if base and base[0] == "class":
                return self.method_of(base[1], expr.attr)
        return None

    def method_of(self, cls_ref: str, meth: str, depth: int = 0) -> tuple[str, str] | None:
        if depth > 5:
            return None
        modname, _, cname = cls_ref.partition(":")
        fid = f"{modname}:{cname}.{meth}"
        if fid in self.funcs:
            return ("func", fid)
        cls = self.modules[modname].classes.get(cname)
        if not cls:
            return None
        for b in cls.bases:
            r = self.resolve_expr(self.modules[modname], b)
            if r and r[0] == "class":
                hit = self.method_of(r[1], meth, depth + 1)
                if hit:
                    return hit
        return None

    def class_of_annotation(self, mod: Module, ann: ast.AST | None) -> tuple[str | None, str | None, list[ast.AST]]:
        """Devuelve (class_ref, nombre_tipo, depends_calls) para una anotación, siguiendo alias Annotated."""
        deps: list[tuple[Module, ast.AST]] = []
        if ann is None:
            return None, None, deps
        if isinstance(ann, ast.Subscript) and _name(ann.value) in ("Annotated", "typing.Annotated"):
            elts = ann.slice.elts if isinstance(ann.slice, ast.Tuple) else [ann.slice]
            for e in elts[1:]:
                if isinstance(e, ast.Call) and _name(e.func).endswith("Depends") and e.args:
                    deps.append((mod, e.args[0]))
            c, t, d = self.class_of_annotation(mod, elts[0])
            return c, t, deps + d
        if isinstance(ann, ast.Subscript):  # Optional[X], list[X]
            inner = ann.slice.elts[0] if isinstance(ann.slice, ast.Tuple) else ann.slice
            c, t, d = self.class_of_annotation(mod, inner)
            return c, t, d
        if isinstance(ann, ast.BinOp):  # X | None
            return self.class_of_annotation(mod, ann.left)
        if isinstance(ann, ast.Constant) and isinstance(ann.value, str):
            try:
                return self.class_of_annotation(mod, ast.parse(ann.value, mode="eval").body)
            except SyntaxError:
                return None, None, deps
        r = self.resolve_expr(mod, ann)
        tname = _name(ann).split(".")[-1]
        if r and r[0] == "class":
            return r[1], tname, deps
        if r and r[0] == "assign":
            amod, _, aname = r[1].partition(":")
            val = self.modules[amod].assigns[aname]
            return self.class_of_annotation(self.modules[amod], val)
        return None, tname, deps


def _name(expr: ast.AST | None) -> str:
    if isinstance(expr, ast.Name):
        return expr.id
    if isinstance(expr, ast.Attribute):
        return f"{_name(expr.value)}.{expr.attr}"
    if isinstance(expr, ast.Call):
        return _name(expr.func) + "()"
    if isinstance(expr, ast.Subscript):
        return _name(expr.value) + "[]"
    return ""


def _const_str(expr: ast.AST | None) -> str | None:
    if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
        return expr.value
    if isinstance(expr, ast.JoinedStr):
        return "".join(v.value if isinstance(v, ast.Constant) else "{?}" for v in expr.values)
    return None


def _kw(call: ast.Call, name: str) -> ast.AST | None:
    for k in call.keywords:
        if k.arg == name:
            return k.value
    return None


# ---------- análisis de cuerpo de funciones ----------
class BodyVisitor(ast.NodeVisitor):
    def __init__(self, proj: Project, fi: FuncInfo, var_types: dict[str, tuple[str | None, str | None]]):
        self.p, self.fi, self.mod = proj, fi, fi.module
        self.var_types = var_types  # var -> (class_ref, type_name)
        self.loop = 0
        self.awaited: set[int] = set()
        self.is_async = isinstance(fi.node, ast.AsyncFunctionDef)
        self.self_attrs = _self_attr_types(proj, fi) if fi.cls else {}
        self.entity_vars: dict[str, str] = {}  # statement = select(Item) -> "Item"

    def _visit_loop(self, node):
        self.loop += 1
        self.generic_visit(node)
        self.loop -= 1

    visit_For = visit_AsyncFor = visit_While = _visit_loop
    visit_ListComp = visit_SetComp = visit_DictComp = visit_GeneratorExp = _visit_loop

    def visit_FunctionDef(self, node):  # funciones anidadas: se analizan como parte del cuerpo
        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Await(self, node):
        if isinstance(node.value, ast.Call):
            self.awaited.add(id(node.value))
        self.generic_visit(node)

    def visit_Assign(self, node):
        if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            ent = _stmt_entity(node.value)
            if ent:
                self.entity_vars[node.targets[0].id] = ent
        if isinstance(node.value, ast.Call) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            r = self.p.resolve_expr(self.mod, node.value.func)
            if r and r[0] == "class":
                self.var_types[node.targets[0].id] = (r[1], r[1].split(":")[1])
            elif _name(node.value.func).split(".")[-1] in ("Client", "AsyncClient", "ClientSession", "Session") and \
                    _name(node.value.func).split(".")[0] in self.mod.imports and \
                    self.mod.imports[_name(node.value.func).split(".")[0]].split(".")[0] in HTTP_LIBS:
                self.var_types[node.targets[0].id] = (None, "httpclient")
        self.generic_visit(node)

    def visit_With(self, node):
        for item in node.items:
            if isinstance(item.optional_vars, ast.Name) and isinstance(item.context_expr, ast.Call):
                fn = _name(item.context_expr.func)
                root = fn.split(".")[0]
                if root in self.mod.imports and self.mod.imports[root].split(".")[0] in HTTP_LIBS:
                    self.var_types[item.optional_vars.id] = (None, "httpclient")
                elif "session" in fn.lower() or "connect" in fn.lower() or "acquire" in fn.lower():
                    self.var_types[item.optional_vars.id] = (None, "Session")
        self.generic_visit(node)

    visit_AsyncWith = visit_With

    def visit_Call(self, node: ast.Call):
        self._classify(node)
        self.generic_visit(node)

    def _receiver_type(self, recv: ast.AST) -> tuple[str | None, str | None]:
        if isinstance(recv, ast.Name) and recv.id in self.var_types:
            return self.var_types[recv.id]
        if isinstance(recv, ast.Attribute) and isinstance(recv.value, ast.Name) and recv.value.id == "self":
            return self.self_attrs.get(recv.attr, (None, None))
        return None, None

    def _effect(self, kind, op, detail, node):
        self.fi.effects.append(Effect(kind, op, detail, self.mod.rel, node.lineno, self.loop > 0, id(node) in self.awaited))

    def _classify(self, node: ast.Call) -> None:
        func = node.func
        fname = _name(func)
        root = fname.split(".")[0]
        imported_root = self.mod.imports.get(root, "").split(".")[0]

        # llamadas resueltas dentro del proyecto
        callee = None
        if isinstance(func, ast.Name):
            r = self.p.resolve_symbol(self.mod, func.id)
            if r and r[0] == "func":
                callee = r[1]
        elif isinstance(func, ast.Attribute):
            recv = func.value
            if isinstance(recv, ast.Name) and recv.id in ("self", "cls") and self.fi.cls:
                r = self.p.method_of(f"{self.mod.name}:{self.fi.cls}", func.attr)
                callee = r[1] if r and r[0] == "func" else None
            else:
                cref, _ = self._receiver_type(recv)
                if cref:
                    r = self.p.method_of(cref, func.attr)
                    callee = r[1] if r and r[0] == "func" else None
                else:
                    r = self.p.resolve_expr(self.mod, func)
                    callee = r[1] if r and r[0] == "func" else None
        if callee:
            self.fi.calls.append((callee, node.lineno, self.loop > 0))
            return

        if not isinstance(func, ast.Attribute):
            if fname in self.mod.imports and self.mod.imports[fname].split(".")[0] in SDK_LIBS and not fname[:1].isupper():
                self._effect("sdk", fname, self.mod.imports[fname], node)
            return
        meth = func.attr
        recv = func.value
        recv_txt = _name(recv).lower()
        _, rtype = self._receiver_type(recv)

        # HTTP externo
        if (imported_root in HTTP_LIBS and meth in HTTP_CALLS | {"Client", "AsyncClient"} and len(fname.split(".")) == 2) \
                or (rtype == "httpclient" and meth in HTTP_CALLS):
            if meth in ("Client", "AsyncClient"):
                return
            lib = imported_root or "httpclient"
            has_timeout = _kw(node, "timeout") is not None
            url = _const_str(node.args[0]) if node.args else _const_str(_kw(node, "url"))
            self._effect("http", meth, f"{lib} {url or '?'}" + ("" if has_timeout else " [sin timeout]"), node)
            return
        if imported_root in SDK_LIBS:
            if meth[:1].isupper():  # constructor (p. ej. SignatureVerifier(...)): no es una llamada de red
                return
            self._effect("sdk", meth, f"{self.mod.imports.get(root)}.{meth}", node)
            return
        if recv_txt.endswith(".instance") or recv_txt == "instance":
            # patrón de plugins (Dispatch): plugin.instance.create(...) se resuelve en runtime
            self._effect("plugin", meth, f"{_name(recv)}.{meth} (destino dinámico)", node)
            return
        # tareas en segundo plano
        if meth in ("delay", "apply_async", "send_task") or (meth == "add_task" and "background" in recv_txt + str(rtype).lower()):
            self._effect("background", meth, fname, node)
            return
        # caché
        if any(h in recv_txt for h in CACHE_HINTS) and meth in CACHE_METHODS:
            self._effect("cache", meth, fname, node)
            return
        # base de datos
        is_db_recv = rtype in DB_TYPES or any(h in recv_txt.split(".")[-1] for h in DB_RECEIVER_HINTS) \
            or recv_txt.endswith("queries")
        if recv_txt.endswith("queries") and meth in self.p.sql_queries:
            op, table = self.p.sql_queries[meth]
            self._effect("db", op, f"{fname}({table})" if table else fname, node)
            return
        if is_db_recv and (meth in DB_READ | DB_WRITE or recv_txt.endswith("queries")):
            op = "write" if meth in DB_WRITE or recv_txt.endswith("queries") and any(
                w in meth for w in ("create", "update", "delete", "add", "remove", "insert")) else "read"
            ent = _entity(node, self.entity_vars)
            self._effect("db", op, f"{fname}({ent})" if ent else fname, node)
            return
        self.fi.unresolved += 1


STMT_BUILDERS = ("select", "query", "update", "delete", "insert")


def _stmt_entity(expr: ast.AST) -> str:
    """Busca select(Model)/update(Model)/... en cualquier parte de una expresión encadenada."""
    for sub in ast.walk(expr):
        if isinstance(sub, ast.Call) and _name(sub.func).split(".")[-1] in STMT_BUILDERS and sub.args:
            a = sub.args[0]
            if isinstance(a, ast.Name) and a.id[:1].isupper():
                return a.id
    return ""


def _entity(call: ast.Call, entity_vars: dict[str, str] | None = None) -> str:
    """Intenta sacar el modelo/tabla de select(Model), query(Model), get(Model, id) o de una variable `statement`."""
    receiver_chain = call.func.value if isinstance(call.func, ast.Attribute) else None
    if receiver_chain is not None:  # db.query(Model).filter(...).first()
        ent = _stmt_entity(receiver_chain)
        if ent:
            return ent
    for a in call.args[:1]:
        if isinstance(a, ast.Name) and a.id[:1].isupper():
            return a.id
        if isinstance(a, ast.Name) and entity_vars and a.id in entity_vars:
            return entity_vars[a.id]
        ent = _stmt_entity(a)
        if ent:
            return ent
    return ""


def _self_attr_types(proj: Project, fi: FuncInfo) -> dict[str, tuple[str | None, str | None]]:
    cls = fi.module.classes.get(fi.cls or "")
    out: dict[str, tuple[str | None, str | None]] = {}
    if not cls:
        return out
    for sub in cls.body:
        if isinstance(sub, ast.FunctionDef) and sub.name == "__init__":
            params = {a.arg: a.annotation for a in sub.args.args + sub.args.kwonlyargs}
            for st in ast.walk(sub):
                if isinstance(st, ast.Assign) and len(st.targets) == 1:
                    t = st.targets[0]
                    if isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) and t.value.id == "self":
                        if isinstance(st.value, ast.Call):
                            r = proj.resolve_expr(fi.module, st.value.func)
                            if r and r[0] == "class":
                                out[t.attr] = (r[1], r[1].split(":")[1])
                        elif isinstance(st.value, ast.Name) and st.value.id in params:
                            c, tn, _ = proj.class_of_annotation(fi.module, params[st.value.id])
                            out[t.attr] = (c, tn)
        if isinstance(sub, ast.AnnAssign) and isinstance(sub.target, ast.Name):
            c, tn, _ = proj.class_of_annotation(fi.module, sub.annotation)
            out[sub.target.id] = (c, tn)
    # métodos/propiedades típicas de repositorios: self.connection
    return out


def _returned_funcs(proj: Project, fi: FuncInfo) -> list[str]:
    """Funciones que una factory retorna por nombre (`return _get_user if required else _get_user_optional`)."""
    out = []
    for st in ast.walk(fi.node):
        if isinstance(st, ast.Return) and st.value is not None:
            for n in ast.walk(st.value):
                if isinstance(n, ast.Name):
                    if n.id in {x.name for x in fi.node.body if isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef))}:
                        continue  # closure anidada: ya forma parte del cuerpo de la factory
                    r = proj.resolve_symbol(fi.module, n.id)
                    if r and r[0] == "func":
                        out.append(r[1])
    return out


def analyze_function(proj: Project, fi: FuncInfo) -> list[str]:
    """Analiza el cuerpo y devuelve las funciones de dependencia (Depends) declaradas en los parámetros."""
    var_types: dict[str, tuple[str | None, str | None]] = {}
    dep_fids: list[str] = []
    args = fi.node.args
    defaults = [None] * (len(args.args) - len(args.defaults)) + list(args.defaults)
    pairs = list(zip(args.args, defaults)) + list(zip(args.kwonlyargs, args.kw_defaults))
    for a, default in pairs:
        cref, tname, deps = proj.class_of_annotation(fi.module, a.annotation)
        if default is not None and isinstance(default, ast.Call) and _name(default.func).endswith("Depends") and default.args:
            deps.append((fi.module, default.args[0]))
        var_types[a.arg] = (cref, tname)
        for dmod, d in deps:
            target = d.func if isinstance(d, ast.Call) else d
            r = proj.resolve_expr(dmod, target)
            if r and r[0] == "func":
                dep_fids.append(r[1])
                if isinstance(d, ast.Call):  # Depends(factory()): la dependencia real es lo que retorna
                    dep_fids.extend(_returned_funcs(proj, proj.funcs[r[1]]))
            elif r and r[0] == "class":  # Depends(Clase) o PermissionsDependency(...)
                m = proj.method_of(r[1], "__call__") or proj.method_of(r[1], "__init__")
                if m:
                    dep_fids.append(m[1])
    v = BodyVisitor(proj, fi, var_types)
    for st in fi.node.body:
        v.visit(st)
    return dep_fids


# ---------- routers y endpoints ----------
def find_routers(proj: Project):
    routers: dict[str, dict] = {}  # "mod:var" -> {prefix, kind}
    edges: list[tuple[str, str, str]] = []  # (parent, child, prefix)

    def router_ref(mod: Module, expr: ast.AST) -> str | None:
        if isinstance(expr, ast.Name):
            r = proj.resolve_symbol(mod, expr.id)
            return r[1] if r and r[0] == "assign" else None
        if isinstance(expr, ast.Attribute):
            r = proj.resolve_expr(mod, expr)
            return r[1] if r and r[0] == "assign" else None
        return None

    for mod in proj.modules.values():
        for name, val in mod.assigns.items():
            if isinstance(val, ast.Call):
                cn = _name(val.func).split(".")[-1]
                if cn in ("APIRouter", "FastAPI"):
                    routers[f"{mod.name}:{name}"] = {"prefix": _const_str(_kw(val, "prefix")) or "", "kind": cn}
    # include_router / mount pueden estar en cualquier parte (p. ej. dentro de get_application())
    for mod in proj.modules.values():
        local_routers: dict[str, str] = {}
        for node in ast.walk(mod.tree):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call) and len(node.targets) == 1 \
                    and isinstance(node.targets[0], ast.Name):
                cn = _name(node.value.func).split(".")[-1]
                if cn in ("APIRouter", "FastAPI") and node.targets[0].id not in mod.assigns:
                    key = f"{mod.name}:{node.targets[0].id}"
                    routers[key] = {"prefix": _const_str(_kw(node.value, "prefix")) or "", "kind": cn}
                    local_routers[node.targets[0].id] = key
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in ("include_router", "mount"):
                pexpr = node.func.value
                parent = local_routers.get(pexpr.id) if isinstance(pexpr, ast.Name) and pexpr.id in local_routers else router_ref(mod, pexpr)
                if node.func.attr == "include_router":
                    cexpr = node.args[0] if node.args else _kw(node, "router")
                    prefix = _const_str(_kw(node, "prefix")) or ""
                else:
                    cexpr = _kw(node, "app") or (node.args[1] if len(node.args) > 1 else None)
                    prefix = _const_str(node.args[0]) if node.args else (_const_str(_kw(node, "path")) or "")
                child = None
                if cexpr is not None:
                    child = local_routers.get(cexpr.id) if isinstance(cexpr, ast.Name) and cexpr.id in local_routers else router_ref(mod, cexpr)
                if parent and child:
                    edges.append((parent, child, prefix or ""))
    return routers, edges


def router_prefixes(routers, edges) -> dict[str, list[tuple[str, bool]]]:
    """Para cada router, sus prefijos completos posibles y si llega a una app FastAPI."""
    parents: dict[str, list[tuple[str, str]]] = {}
    for p, c, pre in edges:
        parents.setdefault(c, []).append((p, pre))
    memo: dict[str, list[tuple[str, bool]]] = {}

    def go(r: str, seen: frozenset) -> list[tuple[str, bool]]:
        if r in memo:
            return memo[r]
        own = routers.get(r, {}).get("prefix", "")
        if routers.get(r, {}).get("kind") == "FastAPI" and r not in parents:
            res = [(own, True)]
        elif r not in parents or r in seen:
            res = [(own, False)]
        else:
            res = []
            for p, pre in parents[r]:
                for pp, rooted in go(p, seen | {r}):
                    res.append((pp + pre + own, rooted))
        memo[r] = res
        return res

    return {r: go(r, frozenset()) for r in routers}


def find_endpoints(proj: Project, routers, prefixes):
    eps = []
    for fid, fi in proj.funcs.items():
        if fi.cls:
            continue
        for dec in fi.node.decorator_list:
            if not (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) and dec.func.attr in HTTP_METHODS):
                continue
            rexpr = dec.func.value
            r = proj.resolve_expr(fi.module, rexpr) if not isinstance(rexpr, ast.Name) else proj.resolve_symbol(fi.module, rexpr.id)
            rkey = r[1] if r and r[0] == "assign" else None
            if rkey not in routers:
                continue
            path = _const_str(dec.args[0]) if dec.args else _const_str(_kw(dec, "path"))
            methods = [dec.func.attr.upper()]
            if dec.func.attr == "api_route":
                m = _kw(dec, "methods")
                methods = [e.value for e in getattr(m, "elts", []) if isinstance(e, ast.Constant)] or ["GET"]
            dep_exprs = []
            deps_kw = _kw(dec, "dependencies")
            for e in getattr(deps_kw, "elts", []):
                if isinstance(e, ast.Call) and _name(e.func).endswith("Depends") and e.args:
                    dep_exprs.append(e.args[0])
            for pre, rooted in prefixes.get(rkey, [("", False)]):
                eps.append({"fid": fid, "methods": methods, "path": pre + (path or ""), "path_resolved": path is not None,
                            "rooted": rooted, "router": rkey, "dep_exprs": dep_exprs,
                            "file": fi.module.rel, "line": fi.node.lineno})
    return eps


def reachable(proj: Project, start: list[str], max_depth: int = 8):
    """BFS por el grafo de llamadas; devuelve efectos con la cadena de llamadas y patrones de riesgo."""
    effects, risks, visited = [], [], set()
    n1_sites: set[tuple[str, int]] = set()
    frontier = [(f, [f], None) for f in start]
    depth = 0
    while frontier and depth <= max_depth:
        nxt = []
        for fid, chain, in_loop_ctx in frontier:
            if fid in visited or fid not in proj.funcs:
                continue
            visited.add(fid)
            fi = proj.funcs[fid]
            is_async = isinstance(fi.node, ast.AsyncFunctionDef)
            for e in fi.effects:
                # el riesgo se reporta en el loop más externo (la línea que hay que cambiar), una vez por sitio
                site = in_loop_ctx or ((e.file, e.line) if e.in_loop else None)
                effects.append({**e.__dict__, "in_loop": bool(site), "via": chain})
                if e.kind == "db" and site and site not in n1_sites:
                    n1_sites.add(site)
                    risks.append({"type": "N+1", "detail": f"{e.detail} se ejecuta una vez por iteración",
                                  "file": site[0], "line": site[1], "db_call": f"{e.file}:{e.line}", "via": chain})
                if e.kind == "http" and "[sin timeout]" in e.detail and e.detail.startswith("requests"):
                    risks.append({"type": "http-sin-timeout", "detail": e.detail, "file": e.file, "line": e.line, "via": chain})
                if is_async and not e.awaited and (e.kind == "http" and e.detail.startswith("requests") or
                                                   e.kind == "db" and e.op == "read" and not e.detail.split("(")[0].endswith((".add", ".delete"))):
                    risks.append({"type": "bloqueante-en-async", "detail": e.detail, "file": e.file, "line": e.line, "via": chain})
            for callee, line, loop in fi.calls:
                nxt.append((callee, chain + [callee], in_loop_ctx or ((fi.module.rel, line) if loop else None)))
        frontier = nxt
        depth += 1
    return effects, risks, visited


def run(root: Path) -> dict:
    t0 = time.perf_counter()
    proj = Project(root)
    proj.load()
    t_parse = time.perf_counter()
    dep_map: dict[str, list[str]] = {}
    for fi in proj.funcs.values():
        dep_map[fi.fid] = analyze_function(proj, fi)
    routers, edges = find_routers(proj)
    prefixes = router_prefixes(routers, edges)
    eps = find_endpoints(proj, routers, prefixes)
    out_eps = []
    for ep in eps:
        fi = proj.funcs[ep["fid"]]
        start = [ep["fid"]] + dep_map.get(ep["fid"], [])
        for d in ep["dep_exprs"]:
            r = proj.resolve_expr(fi.module, d.func if isinstance(d, ast.Call) else d)
            if r and r[0] == "func":
                start.append(r[1])
            elif r and r[0] == "class":
                m = proj.method_of(r[1], "__call__")
                if m:
                    start.append(m[1])
        # las dependencias de las dependencias también corren
        for s in list(start):
            start.extend(x for x in dep_map.get(s, []) if x not in start)
        effects, risks, visited = reachable(proj, start)
        kinds = sorted({e["kind"] for e in effects})
        out_eps.append({
            "method": ",".join(ep["methods"]), "path": ep["path"], "handler": ep["fid"],
            "file": ep["file"], "line": ep["line"], "rooted": ep["rooted"], "path_resolved": ep["path_resolved"],
            "touches": kinds,
            "db_in_handler": any(e["kind"] == "db" and e["via"][0] == ep["fid"] for e in effects),
            "db_ops": sorted({e["op"] for e in effects if e["kind"] == "db"}),
            "entities": sorted({e["detail"].split("(")[1].rstrip(")") for e in effects if e["kind"] == "db" and "(" in e["detail"]}),
            "functions_reached": len(visited),
            "effects": [{k: e[k] for k in ("kind", "op", "detail", "file", "line", "via")} for e in effects],
            "risks": risks,
        })
    t_end = time.perf_counter()
    n = len(out_eps)
    with_db = sum(1 for e in out_eps if "db" in e["touches"])
    return {
        "repo": str(root),
        "stats": {
            "files": len(proj.modules), "functions": len(proj.funcs), "parse_errors": len(proj.parse_errors),
            "routers": len(routers), "include_edges": len(edges),
            "endpoints": n, "endpoints_rooted": sum(e["rooted"] for e in out_eps),
            "endpoints_with_db": with_db, "endpoints_with_db_in_handler": sum(e["db_in_handler"] for e in out_eps),
            "endpoints_with_entity": sum(bool(e["entities"]) for e in out_eps),"endpoints_with_cache": sum("cache" in e["touches"] for e in out_eps),
            "endpoints_with_http": sum(bool({"http", "sdk"} & set(e["touches"])) for e in out_eps),
            "endpoints_with_plugin": sum("plugin" in e["touches"] for e in out_eps),
            "endpoints_with_background": sum("background" in e["touches"] for e in out_eps),
            "risks": sum(len(e["risks"]) for e in out_eps),
            "seconds_parse": round(t_parse - t0, 3), "seconds_total": round(t_end - t0, 3),
        },
        "endpoints": out_eps,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("repo", type=Path)
    ap.add_argument("-o", "--out", type=Path)
    args = ap.parse_args()
    res = run(args.repo.resolve())
    txt = json.dumps(res, indent=2, ensure_ascii=False)
    if args.out:
        args.out.write_text(txt, encoding="utf-8")
    json.dump(res["stats"], sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
