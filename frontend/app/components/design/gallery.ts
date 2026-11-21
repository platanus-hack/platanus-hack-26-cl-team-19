export const galleryGroups = [
  "Composición",
  "Editor",
  "Dominio",
  "Primitivas",
] as const;

export type GalleryGroup = (typeof galleryGroups)[number];
