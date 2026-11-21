<script lang="ts">
import MarkdownIt from "markdown-it";

const markdown = new MarkdownIt({ html: false, breaks: true }).disable("image");

markdown.validateLink = (href) => {
  const url = URL.parse(href, "https://branchpoint.invalid");
  return !!url && ["https:", "http:", "mailto:"].includes(url.protocol);
};
</script>

<script setup lang="ts">
const props = defineProps<{ text: string }>();
const rendered = computed(() => markdown.render(props.text));
</script>

<template>
  <div class="min-w-0 text-sm leading-relaxed wrap-anywhere">
    <span class="sr-only">Agente: </span>
    <!-- Only parser-generated HTML. Raw HTML and image rendering are disabled. -->
    <!-- eslint-disable-next-line vue/no-v-html -->
    <div class="agent-markdown" v-html="rendered" />
  </div>
</template>

<style scoped>
.agent-markdown > :deep(* + *) {
  margin-block-start: 0.65rem;
}

.agent-markdown :deep(:is(h1, h2, h3, h4, h5, h6)) {
  font-weight: 600;
  line-height: 1.35;
}

.agent-markdown :deep(:is(h1, h2)) {
  font-size: 1rem;
}

.agent-markdown :deep(ul) {
  list-style-type: disc;
  padding-inline-start: 1.25rem;
}

.agent-markdown :deep(ol) {
  list-style-type: decimal;
  padding-inline-start: 1.25rem;
}

.agent-markdown :deep(li + li) {
  margin-block-start: 0.2rem;
}

.agent-markdown :deep(a) {
  text-decoration: underline;
  text-underline-offset: 0.15em;
}

.agent-markdown :deep(:not(pre) > code) {
  padding: 0.1em 0.25em;
  border-radius: 0.25rem;
  background: var(--muted);
}

.agent-markdown :deep(pre) {
  overflow-x: auto;
  padding: 0.65rem;
  border: 1px solid var(--border);
  border-radius: 0.375rem;
  background: var(--muted);
  font-size: 0.75rem;
  white-space: pre;
  overflow-wrap: normal;
}

.agent-markdown :deep(blockquote) {
  border-inline-start: 2px solid var(--border);
  padding-inline-start: 0.75rem;
  color: var(--muted-foreground);
}
</style>
