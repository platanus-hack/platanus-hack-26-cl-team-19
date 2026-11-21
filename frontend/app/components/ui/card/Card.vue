<script setup lang="ts">
import type { HTMLAttributes } from "vue";
import { cn } from "cn";

const props = withDefaults(
  defineProps<{
    class?: HTMLAttributes["class"];
    size?: "default" | "sm";
  }>(),
  {
    size: "default",
    class: undefined,
  },
);
</script>

<template>
  <div
    data-slot="card"
    :data-size="size"
    :class="
      cn(
        'group/card flex flex-col gap-6 overflow-hidden rounded-lg border border-border bg-card py-6 text-sm text-card-foreground has-[>img:first-child]:pt-0 data-[size=sm]:gap-4 data-[size=sm]:py-4',
        props.class,
      )
    "
  >
    <slot />
  </div>
</template>
