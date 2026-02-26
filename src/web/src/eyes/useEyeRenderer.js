/**
 * eyes/useEyeRenderer.js
 *
 * Two-level cache strategy:
 *
 *   Level 1 — JSON cache (faceCache):
 *     Persists across remounts. face name → parsed JSON object.
 *     Populated on first fetch, never evicted.
 *
 *   Level 2 — Bitmap cache (bitmapCache):
 *     OffscreenCanvas per named base face, rendered once at current canvas
 *     dimensions. On render, base faces blit with ctx.drawImage() — O(1).
 *     Invalidated when canvas size changes (resize / first mount).
 *     Interpolated transition frames are NEVER cached — they are ephemeral.
 *
 * Queue item shape:
 *   { faceData: object, baseName: string|null }
 *   baseName is set only for named base faces; null for interpolated frames.
 */

import { useCallback, useEffect, useRef } from 'react';
import { drawFace } from './drawFace';
import { getInBetweenFaces } from './interpolation';

const TRANSITION_STEPS = 8;
const BLINK_STEPS = 6;
const BLINK_MIN_MS = 1000;
const BLINK_MAX_MS = 2000;
const FACES_ENDPOINT = '/api/faces';

// ── Level 1: JSON cache (module-level, survives remounts) ────────────────────

const faceCache = new Map(); // name → faceData

async function loadFace(name) {
    if (faceCache.has(name)) return faceCache.get(name);
    const res = await fetch(`${FACES_ENDPOINT}/${name}`);
    if (!res.ok) throw new Error(`Face not found: ${name}`);
    const data = await res.json();
    faceCache.set(name, data);
    return data;
}

const PRELOAD_FACES = [
    'neutral', 'neutral_closed',
    'joy', 'joy_closed',
    'joy_blush', 'joy_blush_closed',
    'sad', 'sad_closed',
    'angry', 'angry_closed',
    'surprise', 'surprise_closed',
    'silly', 'silly_closed',
    'wink',
];

// ── Hook ─────────────────────────────────────────────────────────────────────

export function useEyeRenderer(canvasRef) {
    const currentFaceData = useRef(null);
    const currentFaceName = useRef('neutral');
    const frameQueue = useRef([]);   // [{ faceData, baseName }]
    const rafId = useRef(null);
    const blinkTimer = useRef(null);

    // Level 2: OffscreenCanvas cache — keyed by face name
    // Invalidated when canvas pixel dimensions change
    const bitmapCache = useRef(new Map()); // name → OffscreenCanvas
    const lastCanvasSize = useRef({ w: 0, h: 0 });

    // ── Bitmap cache helpers ─────────────────────────────────────────────────

    /** Returns cached OffscreenCanvas for a base face, or null if stale/absent. */
    const getCachedBitmap = useCallback((name, w, h) => {
        const size = lastCanvasSize.current;
        if (size.w !== w || size.h !== h) return null; // size changed → stale
        return bitmapCache.current.get(name) ?? null;
    }, []);

    /**
     * Renders faceData into an OffscreenCanvas and stores it.
     * Also updates lastCanvasSize so subsequent calls know dimensions are fresh.
     */
    const cacheBitmap = useCallback((name, faceData, w, h) => {
        const osc = new OffscreenCanvas(w, h);
        const octx = osc.getContext('2d');
        drawFace(octx, w, h, faceData);
        bitmapCache.current.set(name, osc);
        lastCanvasSize.current = { w, h };
        return osc;
    }, []);

    /** Clears bitmap cache (called on canvas resize). */
    const invalidateBitmaps = useCallback(() => {
        bitmapCache.current.clear();
    }, []);

    // ── Rendering ────────────────────────────────────────────────────────────

    const renderFrame = useCallback(({ faceData, baseName }) => {
        const canvas = canvasRef.current;
        if (!canvas || !faceData) return;

        const w = canvas.width;
        const h = canvas.height;
        if (w === 0 || h === 0) return;

        // Detect canvas resize → invalidate bitmap cache
        if (w !== lastCanvasSize.current.w || h !== lastCanvasSize.current.h) {
            invalidateBitmaps();
            lastCanvasSize.current = { w, h };
        }

        const ctx = canvas.getContext('2d');

        if (baseName) {
            // Base face — use or populate bitmap cache
            let osc = getCachedBitmap(baseName, w, h);
            if (!osc) osc = cacheBitmap(baseName, faceData, w, h);
            ctx.drawImage(osc, 0, 0); // O(1) blit
        } else {
            // Interpolated transition frame — draw directly, no caching
            drawFace(ctx, w, h, faceData);
        }
    }, [canvasRef, getCachedBitmap, cacheBitmap, invalidateBitmaps]);

    // ── rAF loop ─────────────────────────────────────────────────────────────

    const loop = useCallback(() => {
        if (frameQueue.current.length > 0) {
            const item = frameQueue.current.shift();
            currentFaceData.current = item.faceData;
            renderFrame(item);
        }
        rafId.current = requestAnimationFrame(loop);
    }, [renderFrame]);

    // ── Face transition ──────────────────────────────────────────────────────

    const setFace = useCallback(async (name) => {
        try {
            const targetData = await loadFace(name);

            const queue = frameQueue.current;
            const origin = queue.length > 0
                ? queue[queue.length - 1].faceData
                : (currentFaceData.current ?? targetData);

            const steps = name.endsWith('_closed') ? BLINK_STEPS : TRANSITION_STEPS;

            // Interpolated frames — ephemeral, baseName: null
            const interp = getInBetweenFaces(origin, targetData, steps);
            for (const fd of interp) {
                queue.push({ faceData: fd, baseName: null });
            }

            // Final target — named base face, will be cached after first render
            queue.push({ faceData: targetData, baseName: name });

            currentFaceName.current = name;
        } catch (err) {
            console.warn(`[EyeRenderer] Cannot transition to "${name}":`, err.message);
        }
    }, []);

    // ── Blink ────────────────────────────────────────────────────────────────

    const scheduleBlink = useCallback(() => {
        const delay = BLINK_MIN_MS + Math.random() * (BLINK_MAX_MS - BLINK_MIN_MS);
        blinkTimer.current = setTimeout(async () => {
            const name = currentFaceName.current;
            if (!name.includes('_closed')) {
                await setFace(`${name}_closed`);
                await setFace(name);
            }
            scheduleBlink();
        }, delay);
    }, [setFace]);

    // ── Lifecycle ─────────────────────────────────────────────────────────────

    useEffect(() => {
        // Pre-warm JSON cache AND pre-render bitmaps in background
        const canvas = canvasRef.current;
        const w = canvas?.width || 400;
        const h = canvas?.height || 200;

        PRELOAD_FACES.forEach(name =>
            loadFace(name)
                .then(data => cacheBitmap(name, data, w, h))
                .catch(() => { })
        );

        // Initial face
        loadFace('neutral').then(data => {
            currentFaceData.current = data;
            renderFrame({ faceData: data, baseName: 'neutral' });
            rafId.current = requestAnimationFrame(loop);
            scheduleBlink();
        });

        return () => {
            cancelAnimationFrame(rafId.current);
            clearTimeout(blinkTimer.current);
        };
    }, [loop, renderFrame, scheduleBlink, cacheBitmap, canvasRef]);

    return { setFace };
}