"""Las entregas de Claude (agente de Claude Code, Fable 5.2) leyendo cada repo en modo CLI (ADR 0002).

Cada arquitectura la armó el agente leyendo el repo con grep y lectura de archivos, la misma información que dan
las tools del analizador. Este archivo solo la escribe en JSON con el schema de submit_architecture; el puntaje
lo calcula score.py.
"""

import json
from pathlib import Path

OUT = Path(__file__).parent


def db(op, shape, entity, detail, file, line, why="consulta del handler", **kw):
    return {"kind": "db", "op": op, "shape": shape, "entity": entity, "detail": detail, "file": file, "line": line,
            "why": why, **kw}  # fmt: skip


def cpu(shape, detail, file, line):
    return {"kind": "cpu", "shape": shape, "detail": detail, "file": file, "line": line, "why": "hash de contraseña"}


def ep(method, path, handler, file, line, effects=(), why="ruta declarada aquí", is_async=False):
    return {"method": method, "path": path, "handler": handler, "file": file, "line": line, "why": why,
            "is_async": is_async, "effects": list(effects)}  # fmt: skip


# ---------- gothinkster/node-express-realworld-example-app (Express + Prisma, montado en /api) ----------
A, AS, P, PS, AR, ARS, T, TS = (
    "src/app/routes/auth/auth.controller.ts", "src/app/routes/auth/auth.service.ts",
    "src/app/routes/profile/profile.controller.ts", "src/app/routes/profile/profile.service.ts",
    "src/app/routes/article/article.controller.ts", "src/app/routes/article/article.service.ts",
    "src/app/routes/tag/tag.controller.ts", "src/app/routes/tag/tag.service.ts",
)  # fmt: skip
node = {
    "framework": "express",
    "language": "typescript",
    "endpoints": [
        ep("GET", "/api/tags", "getTags", T, 13, [db("read", "range", "Tag", "prisma.tag.findMany", TS, 16)], is_async=True),
        ep("POST", "/api/users", "createUser", A, 14, [
            db("read", "lookup", "User", "prisma.user.findUnique por email", AS, 10),
            db("read", "lookup", "User", "prisma.user.findUnique por username", AS, 19),
            cpu("password_hash_bcrypt", "bcrypt.hash(password, 10)", AS, 58),
            db("write", "commit", "User", "prisma.user.create", AS, 60)], is_async=True),
        ep("POST", "/api/users/login", "login", A, 30, [
            db("read", "lookup", "User", "prisma.user.findUnique por email", AS, 96),
            cpu("password_hash_bcrypt", "bcrypt.compare", AS, 111)], is_async=True),
        ep("GET", "/api/user", "getCurrentUser", A, 45, [db("read", "pk", "User", "prisma.user.findUnique por id", AS, 132)], is_async=True),
        ep("PUT", "/api/user", "updateUser", A, 61, [db("write", "commit", "User", "prisma.user.update", AS, 159)], is_async=True),
        ep("GET", "/api/profiles/{username}", "getProfile", P, 14, [db("read", "lookup", "User", "prisma.user.findUnique por username", PS, 6)], is_async=True),
        ep("POST", "/api/profiles/{username}/follow", "followUser", P, 34, [db("write", "commit", "User", "prisma.user.update (followedBy)", PS, 23)], is_async=True),
        ep("DELETE", "/api/profiles/{username}/follow", "unfollowUser", P, 54, [db("write", "commit", "User", "prisma.user.update (followedBy)", PS, 43)], is_async=True),
        ep("GET", "/api/articles", "getArticles", AR, 30, [
            db("read", "count", "Article", "prisma.article.count con filtros", ARS, 71),
            db("read", "range", "Article", "prisma.article.findMany con take/skip", ARS, 77)], is_async=True),
        ep("GET", "/api/articles/feed", "getFeed", AR, 45, [
            db("read", "count", "Article", "prisma.article.count del feed", ARS, 114),
            db("read", "range", "Article", "prisma.article.findMany del feed", ARS, 122)], is_async=True),
        ep("POST", "/api/articles", "createArticle", AR, 71, [
            db("read", "lookup", "Article", "prisma.article.findUnique por título", ARS, 180),
            db("write", "commit", "Article", "prisma.article.create", ARS, 197)], is_async=True),
        ep("GET", "/api/articles/{slug}", "getArticle", AR, 87, [db("read", "lookup", "Article", "prisma.article.findUnique por slug", ARS, 242)], is_async=True),
        ep("PUT", "/api/articles/{slug}", "updateArticle", AR, 110, [
            db("read", "lookup", "Article", "prisma.article.findFirst por slug", ARS, 292),
            db("read", "lookup", "Article", "prisma.article.findFirst por título", ARS, 320),
            db("write", "commit", "Article", "prisma.article.update", ARS, 345)], is_async=True),
        ep("DELETE", "/api/articles/{slug}", "deleteArticle", AR, 129, [
            db("read", "lookup", "Article", "prisma.article.findFirst por slug", ARS, 386),
            db("write", "commit", "Article", "prisma.article.delete", ARS, 409)], is_async=True),
        ep("GET", "/api/articles/{slug}/comments", "getCommentsByArticle", AR, 149, [db("read", "lookup", "Article", "prisma.article.findUnique con comments", ARS, 433)], is_async=True),
        ep("POST", "/api/articles/{slug}/comments", "addComment", AR, 170, [
            db("read", "lookup", "Article", "prisma.article.findUnique por slug", ARS, 478),
            db("write", "commit", "Comment", "prisma.comment.create", ARS, 487)], is_async=True),
        ep("DELETE", "/api/articles/{slug}/comments/{id}", "deleteComment", AR, 190, [
            db("read", "lookup", "Comment", "prisma.comment.findFirst", ARS, 528),
            db("write", "commit", "Comment", "prisma.comment.delete", ARS, 555)], is_async=True),
        ep("POST", "/api/articles/{slug}/favorite", "favoriteArticle", AR, 210, [db("write", "commit", "Article", "prisma.article.update (favoritedBy)", ARS, 563)], is_async=True),
        ep("DELETE", "/api/articles/{slug}/favorite", "unfavoriteArticle", AR, 230, [db("write", "commit", "Article", "prisma.article.update (favoritedBy)", ARS, 609)], is_async=True),
    ],
    "components": [{"name": "postgres", "role": "db", "technology": "Postgres (Prisma)", "file": ARS, "line": 77,
                    "why": "las consultas Prisma de los services"}],
}  # fmt: skip

# ---------- gothinkster/django-realworld-example-app (Django REST, montado en /api) ----------
V, AU, AV, PV, PU, AM, PM, ASZ = (
    "conduit/apps/articles/urls.py", "conduit/apps/authentication/urls.py", "conduit/apps/articles/views.py",
    "conduit/apps/profiles/views.py", "conduit/apps/profiles/urls.py", "conduit/apps/authentication/views.py",
    "conduit/apps/profiles/models.py", "conduit/apps/authentication/serializers.py",
)  # fmt: skip
django = {
    "framework": "django",
    "language": "python",
    "endpoints": [
        ep("GET", "/api/user", "UserRetrieveUpdateAPIView.retrieve", AU, 8, why="url('^user/?$') sobre UserRetrieveUpdateAPIView"),
        ep("PUT", "/api/user", "UserRetrieveUpdateAPIView.update", AU, 8, [db("write", "commit", "User", "serializer.save()", AM, 82)]),
        ep("PATCH", "/api/user", "UserRetrieveUpdateAPIView.update", AU, 8, [db("write", "commit", "User", "serializer.save()", AM, 82)]),
        ep("POST", "/api/users", "RegistrationAPIView.post", AU, 9, [db("write", "commit", "User", "serializer.save()", AM, 27)]),
        ep("POST", "/api/users/login", "LoginAPIView.post", AU, 10, [db("read", "lookup", "User", "authenticate(username=email)", ASZ, 69)]),
        ep("GET", "/api/profiles/{username}", "ProfileRetrieveAPIView.retrieve", PU, 6, [db("read", "lookup", "Profile", "Profile.objects.get(user__username)", PV, 23)]),
        ep("POST", "/api/profiles/{username}/follow", "ProfileFollowAPIView.post", PU, 7, [
            db("read", "lookup", "Profile", "Profile.objects.get(user__username)", PV, 59),
            db("write", "commit", "Profile", "self.follows.add(profile)", PM, 46)]),
        ep("DELETE", "/api/profiles/{username}/follow", "ProfileFollowAPIView.delete", PU, 7, [
            db("read", "lookup", "Profile", "Profile.objects.get(user__username)", PV, 43),
            db("write", "commit", "Profile", "self.follows.remove(profile)", PM, 50)]),
        ep("GET", "/api/articles", "ArticleViewSet.list", V, 11, [
            db("read", "count", "Article", "paginate_queryset (COUNT)", AV, 61),
            db("read", "range", "Article", "paginate_queryset(get_queryset())", AV, 61)], why="router.register('articles')"),
        ep("POST", "/api/articles", "ArticleViewSet.create", V, 11, [db("write", "commit", "Article", "serializer.save()", AV, 55)], why="router.register('articles')"),
        ep("GET", "/api/articles/{slug}", "ArticleViewSet.retrieve", V, 11, [db("read", "lookup", "Article", "queryset.get(slug=slug)", AV, 75)], why="router.register('articles')"),
        ep("PUT", "/api/articles/{slug}", "ArticleViewSet.update", V, 11, [
            db("read", "lookup", "Article", "queryset.get(slug=slug)", AV, 91),
            db("write", "commit", "Article", "serializer.save()", AV, 104)], why="router.register('articles'): update"),
        ep("GET", "/api/articles/feed", "ArticlesFeedAPIView.list", V, 16, [db("read", "range", "Article", "paginate_queryset del feed", AV, 224)]),
        ep("POST", "/api/articles/{article_slug}/favorite", "ArticlesFavoriteAPIView.post", V, 18, [
            db("read", "lookup", "Article", "Article.objects.get(slug)", AV, 185),
            db("write", "commit", "Article", "self.favorites.add(article)", PM, 62)]),
        ep("DELETE", "/api/articles/{article_slug}/favorite", "ArticlesFavoriteAPIView.delete", V, 18, [
            db("read", "lookup", "Article", "Article.objects.get(slug)", AV, 170),
            db("write", "commit", "Article", "self.favorites.remove(article)", PM, 66)]),
        ep("GET", "/api/articles/{article_slug}/comments", "CommentsListCreateAPIView.list", V, 21, [db("read", "range", "Comment", "queryset.filter(article__slug)", AV, 126)]),
        ep("POST", "/api/articles/{article_slug}/comments", "CommentsListCreateAPIView.create", V, 21, [
            db("read", "lookup", "Article", "Article.objects.get(slug)", AV, 133),
            db("write", "commit", "Comment", "serializer.save()", AV, 139)]),
        ep("DELETE", "/api/articles/{article_slug}/comments/{comment_pk}", "CommentsDestroyAPIView.destroy", V, 24, [
            db("read", "pk", "Comment", "Comment.objects.get(pk)", AV, 151),
            db("write", "commit", "Comment", "comment.delete()", AV, 155)]),
        ep("GET", "/api/tags", "TagListAPIView.list", V, 27, [db("read", "scan", "Tag", "Tag.objects.all()", AV, 203)]),
    ],
}  # fmt: skip

# ---------- nsidnev/fastapi-realworld-example-app (FastAPI + asyncpg, prefijo /api) ----------
R = "app/api/routes"
RW = {
    "framework": "fastapi",
    "language": "python",
    "endpoints": [
        ep("POST", "/api/users/login", "login", f"{R}/authentication.py", 22, [db("read", "lookup", "User", "users_repo.get_user_by_email", f"{R}/authentication.py", 34)], is_async=True),
        ep("POST", "/api/users", "register", f"{R}/authentication.py", 56, [db("write", "commit", "User", "users_repo.create_user", f"{R}/authentication.py", 79)], is_async=True),
        ep("GET", "/api/user", "retrieve_current_user", f"{R}/users.py", 18, is_async=True),
        ep("PUT", "/api/user", "update_current_user", f"{R}/users.py", 38, [db("write", "commit", "User", "users_repo.update_user", f"{R}/users.py", 59)], is_async=True),
        ep("GET", "/api/profiles/{username}", "retrieve_profile_by_username", f"{R}/profiles.py", 16, [db("read", "lookup", "Profile", "profiles_repo.get_profile_by_username", "app/api/dependencies/profiles.py", 21)], is_async=True),
        ep("POST", "/api/profiles/{username}/follow", "follow_for_user", f"{R}/profiles.py", 27, [db("write", "commit", "Follower", "profiles_repo.add_user_into_followers", f"{R}/profiles.py", 49)], is_async=True),
        ep("DELETE", "/api/profiles/{username}/follow", "unsubscribe_from_user", f"{R}/profiles.py", 57, [db("write", "commit", "Follower", "profiles_repo.remove_user_from_followers", f"{R}/profiles.py", 79)], is_async=True),
        ep("GET", "/api/articles/feed", "get_articles_for_user_feed", f"{R}/articles/articles_common.py", 22, [db("read", "range", "Article", "articles_repo.get_articles_for_user_feed", f"{R}/articles/articles_common.py", 33)], is_async=True),
        ep("POST", "/api/articles/{slug}/favorite", "mark_article_as_favorite", f"{R}/articles/articles_common.py", 47, [db("write", "commit", "Favorite", "articles_repo.add_article_into_favorites", f"{R}/articles/articles_common.py", 58)], is_async=True),
        ep("DELETE", "/api/articles/{slug}/favorite", "remove_article_from_favorites", f"{R}/articles/articles_common.py", 77, [db("write", "commit", "Favorite", "articles_repo.remove_article_from_favorites", f"{R}/articles/articles_common.py", 88)], is_async=True),
        ep("GET", "/api/articles", "list_articles", f"{R}/articles/articles_resource.py", 30, [db("read", "range", "Article", "articles_repo.filter_articles", f"{R}/articles/articles_resource.py", 36)], is_async=True),
        ep("POST", "/api/articles", "create_new_article", f"{R}/articles/articles_resource.py", 53, [db("write", "commit", "Article", "articles_repo.create_article", f"{R}/articles/articles_resource.py", 71)], is_async=True),
        ep("GET", "/api/articles/{slug}", "retrieve_article_by_slug", f"{R}/articles/articles_resource.py", 82, [db("read", "lookup", "Article", "articles_repo.get_article_by_slug", "app/api/dependencies/articles.py", 43)], is_async=True),
        ep("PUT", "/api/articles/{slug}", "update_article_by_slug", f"{R}/articles/articles_resource.py", 89, [db("write", "commit", "Article", "articles_repo.update_article", f"{R}/articles/articles_resource.py", 101)], is_async=True),
        ep("DELETE", "/api/articles/{slug}", "delete_article_by_slug", f"{R}/articles/articles_resource.py", 109, [db("write", "commit", "Article", "articles_repo.delete_article", f"{R}/articles/articles_resource.py", 120)], is_async=True),
        ep("GET", "/api/articles/{slug}/comments", "list_comments_for_article", f"{R}/comments.py", 26, [db("read", "range", "Comment", "comments_repo.get_comments_for_article", f"{R}/comments.py", 36)], is_async=True, why="prefijo /articles/{slug}/comments en api.py:14"),
        ep("POST", "/api/articles/{slug}/comments", "create_comment_for_article", f"{R}/comments.py", 40, [db("write", "commit", "Comment", "comments_repo.create_comment_for_article", f"{R}/comments.py", 52)], is_async=True, why="prefijo /articles/{slug}/comments en api.py:14"),
        ep("DELETE", "/api/articles/{slug}/comments/{comment_id}", "delete_comment_from_article", f"{R}/comments.py", 60, [
            db("read", "pk", "Comment", "comments_repo.get_comment_by_id", "app/api/dependencies/comments.py", 27),
            db("write", "commit", "Comment", "comments_repo.delete_comment", f"{R}/comments.py", 71)], is_async=True),
        ep("GET", "/api/tags", "get_all_tags", f"{R}/tags.py", 10, [db("read", "scan", "Tag", "tags_repo.get_all_tags", f"{R}/tags.py", 14)], is_async=True),
    ],
    "components": [{"name": "postgres", "role": "db", "technology": "Postgres (asyncpg)", "file": "docker-compose.yml", "line": 1,
                    "why": "servicio de la base en el compose"}],
}  # fmt: skip

# ---------- fastapi/full-stack-fastapi-template (FastAPI + SQLModel, prefijo /api/v1) ----------
B = "backend/app/api/routes"
ITEMS, U, L = f"{B}/items.py", f"{B}/users.py", f"{B}/login.py"
SEC = "password_hash"
full = {
    "framework": "fastapi",
    "language": "python",
    "endpoints": [
        ep("GET", "/api/v1/items/", "read_items", ITEMS, 13, [
            db("read", "count", "Item", "session.exec(count_statement)", ITEMS, 23),
            db("read", "range", "Item", "session.exec(select(Item).offset.limit)", ITEMS, 27)]),
        ep("GET", "/api/v1/items/{id}", "read_item", ITEMS, 48, [db("read", "pk", "Item", "session.get(Item, id)", ITEMS, 53)]),
        ep("POST", "/api/v1/items/", "create_item", ITEMS, 61, [db("write", "stage", "Item", "session.add(item)", ITEMS, 69), db("write", "commit", "Item", "session.commit()", ITEMS, 70)]),
        ep("PUT", "/api/v1/items/{id}", "update_item", ITEMS, 75, [db("read", "pk", "Item", "session.get(Item, id)", ITEMS, 86), db("write", "commit", "Item", "session.commit()", ITEMS, 94)]),
        ep("DELETE", "/api/v1/items/{id}", "delete_item", ITEMS, 99, [db("read", "pk", "Item", "session.get(Item, id)", ITEMS, 106), db("write", "commit", "Item", "session.commit()", ITEMS, 112)]),
        ep("POST", "/api/v1/login/access-token", "login_access_token", L, 23, [db("read", "lookup", "User", "crud.authenticate (por email + verify_password)", L, 30)]),
        ep("POST", "/api/v1/login/test-token", "test_token", L, 45),
        ep("POST", "/api/v1/password-recovery/{email}", "recover_password", L, 53, [
            db("read", "lookup", "User", "crud.get_user_by_email", L, 58),
            {"kind": "external", "service": "SMTP", "detail": "send_email", "file": L, "line": 67, "why": "envía el correo"}]),
        ep("POST", "/api/v1/reset-password/", "reset_password", L, 77, [db("read", "lookup", "User", "crud.get_user_by_email", L, 85), db("write", "commit", "User", "crud.update_user", L, 92)]),
        ep("POST", "/api/v1/password-recovery-html-content/{email}", "recover_password_html_content", L, 100, [db("read", "lookup", "User", "crud.get_user_by_email", L, 109)]),
        ep("POST", "/api/v1/private/users/", "create_user", f"{B}/private.py", 23, [
            cpu(SEC, "get_password_hash", f"{B}/private.py", 32), db("write", "commit", "User", "session.commit()", f"{B}/private.py", 36)]),
        ep("GET", "/api/v1/users/", "read_users", U, 32, [db("read", "count", "User", "session.exec(count_statement)", U, 43), db("read", "range", "User", "session.exec(select(User))", U, 48)]),
        ep("POST", "/api/v1/users/", "create_user", U, 54, [
            db("read", "lookup", "User", "crud.get_user_by_email", U, 61), db("write", "commit", "User", "crud.create_user", U, 68),
            {"kind": "external", "service": "SMTP", "detail": "send_email", "file": U, "line": 73, "why": "correo de cuenta nueva"}]),
        ep("PATCH", "/api/v1/users/me", "update_user_me", U, 81, [db("read", "lookup", "User", "crud.get_user_by_email", U, 90), db("write", "commit", "User", "session.commit()", U, 98)]),
        ep("PATCH", "/api/v1/users/me/password", "update_password_me", U, 103, [
            cpu(SEC, "verify_password", U, 110), cpu(SEC, "get_password_hash", U, 117), db("write", "commit", "User", "session.commit()", U, 120)]),
        ep("GET", "/api/v1/users/me", "read_user_me", U, 124),
        ep("DELETE", "/api/v1/users/me", "delete_user_me", U, 132, [db("write", "commit", "User", "session.delete + commit", U, 142)]),
        ep("POST", "/api/v1/users/signup", "register_user", U, 146, [db("read", "lookup", "User", "crud.get_user_by_email", U, 151), db("write", "commit", "User", "crud.create_user", U, 158)]),
        ep("GET", "/api/v1/users/{user_id}", "read_user_by_id", U, 162, [db("read", "pk", "User", "session.get(User, user_id)", U, 169)]),
        ep("PATCH", "/api/v1/users/{user_id}", "update_user", U, 182, [
            db("read", "pk", "User", "session.get(User, user_id)", U, 197), db("read", "lookup", "User", "crud.get_user_by_email", U, 204),
            db("write", "commit", "User", "crud.update_user", U, 210)]),
        ep("DELETE", "/api/v1/users/{user_id}", "delete_user", U, 214, [
            db("read", "pk", "User", "session.get(User, user_id)", U, 221), db("write", "commit", "User", "session.commit()", U, 231)]),
        ep("POST", "/api/v1/utils/test-email/", "test_email", f"{B}/utils.py", 11, [
            {"kind": "external", "service": "SMTP", "detail": "send_email", "file": f"{B}/utils.py", "line": 21, "why": "correo de prueba"}]),
        ep("GET", "/api/v1/utils/health-check/", "health_check", f"{B}/utils.py", 29, is_async=True),
    ],
    "components": [{"name": "db", "role": "db", "technology": "Postgres (SQLModel)", "file": "compose.yml", "line": 1,
                    "why": "servicio db del compose"}],
}  # fmt: skip

for name, arch in {
    "node-express-realworld-example-app": node,
    "django-realworld-example-app": django,
    "fastapi-realworld-example-app": RW,
    "full-stack-fastapi-template": full,
}.items():
    (OUT / f"{name}.json").write_text(json.dumps(arch, ensure_ascii=False, indent=1) + "\n")
    print(name, len(arch["endpoints"]))
