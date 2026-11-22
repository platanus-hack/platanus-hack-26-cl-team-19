import type { MaybeRefOrGetter } from "vue";

export const MIN_ZOOM = 0.25;
export const MAX_ZOOM = 3;
const BUTTON_STEP = 1.2;
/** Píxeles que hay que arrastrar para que deje de contar como clic. */
const DRAG_THRESHOLD = 3;

interface Size {
  width: number;
  height: number;
}

/**
 * Mueve y amplía un lienzo. `zoom` es relativo al ajuste: 1 es el diagrama completo a la
 * vista, centrado. `pan` desplaza ese centro en píxeles de pantalla.
 */
export function usePanZoom(
  viewport: MaybeRefOrGetter<Size>,
  content: MaybeRefOrGetter<Size>,
) {
  const zoom = ref(1);
  const pan = ref({ x: 0, y: 0 });

  const fit = computed(() => {
    const view = toValue(viewport);
    const size = toValue(content);
    if (!view.width || !view.height || !size.width || !size.height) return 1;
    return Math.min(1, view.width / size.width, view.height / size.height);
  });
  const scale = computed(() => fit.value * zoom.value);

  function offsetFor(nextScale: number) {
    const view = toValue(viewport);
    const size = toValue(content);
    return {
      x: (view.width - size.width * nextScale) / 2,
      y: (view.height - size.height * nextScale) / 2,
    };
  }

  /** Esquina superior izquierda del contenido, en píxeles del viewport. */
  const translate = computed(() => {
    const offset = offsetFor(scale.value);
    return { x: offset.x + pan.value.x, y: offset.y + pan.value.y };
  });

  /** Cambia el zoom dejando fijo el punto del viewport `at` (por defecto, el centro). */
  function zoomTo(next: number, at?: { x: number; y: number }) {
    const view = toValue(viewport);
    const point = at ?? { x: view.width / 2, y: view.height / 2 };
    const clamped = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, next));
    const before = translate.value;
    const contentX = (point.x - before.x) / scale.value;
    const contentY = (point.y - before.y) / scale.value;
    const nextScale = fit.value * clamped;
    const offset = offsetFor(nextScale);
    zoom.value = clamped;
    pan.value = {
      x: point.x - contentX * nextScale - offset.x,
      y: point.y - contentY * nextScale - offset.y,
    };
  }

  const zoomIn = () => zoomTo(zoom.value * BUTTON_STEP);
  const zoomOut = () => zoomTo(zoom.value / BUTTON_STEP);
  function reset() {
    zoom.value = 1;
    pan.value = { x: 0, y: 0 };
  }
  const isReset = computed(
    () => zoom.value === 1 && pan.value.x === 0 && pan.value.y === 0,
  );

  function onWheel(event: WheelEvent, rect: DOMRect) {
    // La rueda del mouse y el pellizco del trackpad (llega con ctrlKey) amplían.
    const factor = Math.exp(-event.deltaY * (event.ctrlKey ? 0.01 : 0.0015));
    zoomTo(zoom.value * factor, {
      x: event.clientX - rect.left,
      y: event.clientY - rect.top,
    });
  }

  let drag: { x: number; y: number; pan: { x: number; y: number } } | null =
    null;
  const dragging = ref(false);
  /** true si el último gesto fue un arrastre, para no tratarlo como clic. */
  let dragged = false;

  function onPointerDown(event: PointerEvent) {
    if (event.button !== 0) return;
    drag = { x: event.clientX, y: event.clientY, pan: { ...pan.value } };
    dragged = false;
  }

  function onPointerMove(event: PointerEvent) {
    if (!drag) return;
    const dx = event.clientX - drag.x;
    const dy = event.clientY - drag.y;
    if (!dragging.value && Math.hypot(dx, dy) < DRAG_THRESHOLD) return;
    if (!dragging.value) {
      dragging.value = true;
      (event.currentTarget as Element | null)?.setPointerCapture?.(
        event.pointerId,
      );
    }
    dragged = true;
    pan.value = { x: drag.pan.x + dx, y: drag.pan.y + dy };
  }

  function onPointerUp() {
    drag = null;
    dragging.value = false;
  }

  /** Consume el arrastre recién terminado: true si el clic que sigue debe ignorarse. */
  function consumeDrag() {
    const was = dragged;
    dragged = false;
    return was;
  }

  return {
    zoom,
    pan,
    scale,
    translate,
    dragging,
    isReset,
    canZoomIn: computed(() => zoom.value < MAX_ZOOM),
    canZoomOut: computed(() => zoom.value > MIN_ZOOM),
    zoomTo,
    zoomIn,
    zoomOut,
    reset,
    onWheel,
    onPointerDown,
    onPointerMove,
    onPointerUp,
    consumeDrag,
  };
}
