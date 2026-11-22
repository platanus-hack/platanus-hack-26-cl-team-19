<script setup lang="ts">
// JAJ-148: dónde corre el componente seleccionado. Elegir otro proveedor o plan crea una versión nueva
// con la operación del catálogo; Simular esa versión usa las especificaciones del plan.
import ProvenanceBadge from "@/components/design/ProvenanceBadge.vue";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  apiCost,
  DEPLOYMENT_TITLES,
  deploymentNote,
  deploymentOps,
  sameDeployment,
  specRows,
  wastedVcpu,
  type ApiSize,
  type DeploymentChoice,
  type DeploymentKind,
  type ProviderOption,
} from "@/services/deployment-options";
import { toProvenance } from "@/services/editor-view";

const props = defineProps<{
  kind: DeploymentKind;
  options: ProviderOption[] | null;
  current: DeploymentChoice | null;
  busy?: boolean;
  /** API: réplicas y memoria de la versión abierta, para calcular el costo del plan elegido. */
  size?: ApiSize;
  /** La versión abierta, para decir de cuál sale la nueva. */
  versionLabel?: string;
}>();
const emit = defineEmits<{
  apply: [ops: Record<string, unknown>[], note: string];
}>();

const providerId = ref("");
const planId = ref("");
const vcpu = ref<number | string>(1);
const replicas = ref<number | string>(1);
const workers = ref<number | string>(1);

function reset() {
  providerId.value = props.current?.provider ?? "";
  planId.value = props.current?.plan ?? "";
  vcpu.value = props.current?.vcpu ?? 1;
  replicas.value = props.current?.replicas ?? 1;
  workers.value = props.current?.workers ?? 1;
}
watch(() => [props.current, props.kind], reset, { immediate: true });

const provider = computed(() =>
  props.options?.find(({ id }) => id === providerId.value),
);
// Al cambiar de proveedor, el primer plan; el actual si es el mismo proveedor.
watch(providerId, (id) => {
  const plans = provider.value?.plans ?? [];
  if (plans.some(({ id: plan }) => plan === planId.value)) return;
  planId.value =
    id === props.current?.provider && props.current?.plan
      ? props.current.plan
      : (plans[0]?.id ?? "");
});

const plan = computed(() =>
  provider.value?.plans.find(({ id }) => id === planId.value),
);
const vcpuNumber = computed(() => Number(vcpu.value));
const replicaNumber = computed(() => Number(replicas.value));
const workerNumber = computed(() => Number(workers.value));
const choice = computed<DeploymentChoice>(() => ({
  provider: providerId.value,
  plan: provider.value?.sized_by_vcpu ? null : planId.value || null,
  vcpu: provider.value?.sized_by_vcpu ? vcpuNumber.value : null,
  ...(props.kind === "api"
    ? { replicas: replicaNumber.value, workers: workerNumber.value }
    : {}),
}));
const rows = computed(() => {
  const specs = {
    ...(plan.value?.specs ??
      (provider.value?.sized_by_vcpu ? (provider.value.example ?? {}) : {})),
  };
  // la API: el costo de todas las réplicas con los vCPU o el plan elegidos, no el de un ejemplo fijo
  if (props.kind === "api" && provider.value && props.size)
    specs.usd_month = apiCost(
      provider.value,
      plan.value,
      vcpuNumber.value,
      replicaNumber.value,
      props.size,
    );
  return specRows(specs);
});
const valid = computed(() => {
  if (!provider.value) return false;
  if (props.kind === "api") {
    const n = replicaNumber.value;
    if (!Number.isInteger(n) || n < 1 || n > 50) return false;
    const w = workerNumber.value;
    if (!Number.isInteger(w) || w < 1 || w > 64) return false;
  }
  if (provider.value.sized_by_vcpu)
    return vcpuNumber.value > 0 && vcpuNumber.value <= 16;
  return !!plan.value;
});
const unchanged = computed(() => sameDeployment(props.current, choice.value));
// vCPU por réplica del plan o los elegidos: con menos workers, sobran
const machineVcpu = computed(() =>
  provider.value?.sized_by_vcpu
    ? vcpuNumber.value
    : (plan.value?.specs.vcpu?.value ?? null),
);
const workersWarning = computed(() =>
  props.kind === "api"
    ? wastedVcpu(workerNumber.value, machineVcpu.value)
    : null,
);
// la procedencia de los workers actuales (del repo, del usuario o por defecto) mientras no se cambien
const workersProvenance = computed(() => {
  const current = props.size?.workers;
  return current && current.value === workerNumber.value
    ? toProvenance(current)
    : null;
});

function apply() {
  if (!valid.value || unchanged.value || !props.options) return;
  emit(
    "apply",
    deploymentOps(props.kind, choice.value),
    deploymentNote(props.kind, choice.value, props.options),
  );
}

const ids = {
  provider: useId(),
  plan: useId(),
  vcpu: useId(),
  replicas: useId(),
  workers: useId(),
};
</script>

<template>
  <section
    aria-labelledby="deployment-heading"
    class="flex flex-col gap-3 text-sm"
  >
    <div class="flex flex-col gap-0.5">
      <h3 id="deployment-heading" class="font-semibold">Dónde corre</h3>
      <p class="text-xs text-muted-foreground">
        {{ DEPLOYMENT_TITLES[kind] }}: el plan define lo que se simula y su
        costo.
      </p>
    </div>

    <p v-if="!options" class="text-xs text-muted-foreground">
      Cargando proveedores…
    </p>

    <template v-else>
      <div class="grid gap-1.5">
        <Label :for="ids.provider">Proveedor</Label>
        <Select v-model="providerId" :disabled="busy">
          <SelectTrigger :id="ids.provider" class="w-full">
            <SelectValue placeholder="Elige un proveedor" />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              <SelectItem
                v-for="option in options"
                :key="option.id"
                :value="option.id"
                >{{ option.label }}</SelectItem
              >
            </SelectGroup>
          </SelectContent>
        </Select>
      </div>

      <div v-if="provider?.sized_by_vcpu" class="grid gap-1.5">
        <Label :for="ids.vcpu">vCPU por réplica</Label>
        <Input
          :id="ids.vcpu"
          v-model="vcpu"
          type="number"
          min="0.25"
          max="16"
          step="0.25"
          :disabled="busy"
        />
        <p class="text-xs text-muted-foreground">
          Se paga por vCPU-hora y GB-hora.
          <template v-if="size"
            >Cada réplica tiene {{ size.memoryGb }} GB.</template
          >
        </p>
      </div>
      <div v-else-if="provider" class="grid gap-1.5">
        <Label :for="ids.plan">Plan</Label>
        <Select v-model="planId" :disabled="busy">
          <SelectTrigger :id="ids.plan" class="w-full">
            <SelectValue placeholder="Elige un plan" />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              <SelectItem
                v-for="option in provider.plans"
                :key="option.id"
                :value="option.id"
                >{{ option.id }}</SelectItem
              >
            </SelectGroup>
          </SelectContent>
        </Select>
      </div>

      <div v-if="kind === 'api' && provider" class="grid gap-1.5">
        <Label :for="ids.replicas">Réplicas</Label>
        <Input
          :id="ids.replicas"
          v-model="replicas"
          type="number"
          min="1"
          max="50"
          step="1"
          :disabled="busy"
        />
        <p class="text-xs text-muted-foreground">
          Máquinas separadas, cada una con
          {{ provider.sized_by_vcpu ? "sus vCPU" : "el plan" }}. El costo y la
          capacidad se multiplican por las réplicas.
        </p>
      </div>

      <div v-if="kind === 'api' && provider" class="grid gap-1.5">
        <div class="flex items-center justify-between gap-2">
          <Label :for="ids.workers">Workers por réplica</Label>
          <ProvenanceBadge
            v-if="workersProvenance"
            :provenance="workersProvenance"
            compact
          />
        </div>
        <Input
          :id="ids.workers"
          v-model="workers"
          type="number"
          min="1"
          max="64"
          step="1"
          :disabled="busy"
        />
        <p class="text-xs text-muted-foreground">
          Procesos de la API en cada réplica (uvicorn o gunicorn --workers).
          Cada uno usa un núcleo como máximo. No cambian el costo.
        </p>
        <p v-if="workersWarning" class="text-xs text-status-at-risk-foreground">
          {{ workersWarning }}
        </p>
      </div>

      <dl v-if="rows.length" class="flex flex-col gap-1.5">
        <div
          v-for="row in rows"
          :key="row.key"
          class="flex items-center justify-between gap-3"
        >
          <dt class="min-w-0 text-muted-foreground">{{ row.label }}</dt>
          <dd class="flex items-center gap-1 whitespace-nowrap">
            <span class="font-mono text-xs tabular-nums">{{ row.text }}</span>
            <ProvenanceBadge
              :provenance="
                toProvenance({
                  value: row.spec.value ?? 0,
                  label: row.spec.label,
                  source: row.spec.source,
                })
              "
              compact
            />
          </dd>
        </div>
      </dl>

      <Button
        size="sm"
        :disabled="busy || !valid || unchanged"
        @click="apply"
        >{{
          unchanged ? "Es el plan actual" : "Crear versión con este plan"
        }}</Button
      >
      <p
        v-if="!unchanged && versionLabel"
        class="text-xs text-muted-foreground"
      >
        Sale de {{ versionLabel }}. Después, Simular usa estas especificaciones.
      </p>
    </template>
  </section>
</template>
