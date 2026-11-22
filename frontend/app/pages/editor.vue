<script setup lang="ts">
import ProjectEditor from "@/components/editor/ProjectEditor.vue";

definePageMeta({
  middleware: "supabase-session",
  key: (route) => route.fullPath,
});
useSeoMeta({ title: "Editor · Branchpoint" });
</script>

<template>
  <ProjectEditor />
</template>
