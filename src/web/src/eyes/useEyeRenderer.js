/**
 * eyes/useEyeRenderer.js
 *
 * Face data is imported statically from faceData.js — no HTTP requests,
 * no server dependency, available instantly on mount.
 *
 * Two-level cache:
 *   Level 1 — FACES map (faceData.js): always in memory, zero latency.
 *   Level 2 — bitmapCache: OffscreenCanvas per named base face, rendered
 *              once at current canvas size. Invalidated on resize.
 *              Interpolated frames are never cached (ephemeral).
 */

import { useCallback, useEffect, useRef } from 'react';
import { drawFace } from './drawFace';
import { FACES } from './faceData';
import { getInBetweenFaces } from './interpolation';

const TRANSITION_STEPS = 6;
const BLINK_STEPS = 0.5;
const BLINK_MIN_MS = 4000;
const BLINK_MAX_MS = 7000;

function getFace(name) {
    const data = FACES[name];
    if (!data) throw new Error(`Face not found: ${name}`);
    return data;
}

export function useEyeRenderer(canvasRef) {
    const currentFaceData = useRef(null);
    const currentFaceName = useRef('neutral');
    const frameQueue = useRef([]);   // [{ faceData, baseName }]
    const rafId = useRef(null);
    const blinkTimer = useRef(null);
    const bitmapCache = useRef(new Map());
    const lastCanvasSize = useRef({ w: 0, h: 0 });

    // ── Bitmap cache ─────────────────────────────────────────────────────────

    const getCachedBitmap = useCallback((name, w, h) => {
        const s = lastCanvasSize.current;
        if (s.w !== w || s.h !== h) return null;
        return bitmapCache.current.get(name) ?? null;
    }, []);

    const cacheBitmap = useCallback((name, faceData, w, h) => {
        const osc = new OffscreenCanvas(w, h);
        drawFace(osc.getContext('2d'), w, h, faceData);
        bitmapCache.current.set(name, osc);
        lastCanvasSize.current = { w, h };
        return osc;
    }, []);

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

        if (w !== lastCanvasSize.current.w || h !== lastCanvasSize.current.h) {
            invalidateBitmaps();
            lastCanvasSize.current = { w, h };
        }

        const ctx = canvas.getContext('2d');
        ctx.clearRect(0, 0, w, h);
        if (baseName) {
            let osc = getCachedBitmap(baseName, w, h);
            if (!osc) osc = cacheBitmap(baseName, faceData, w, h);
            ctx.drawImage(osc, 0, 0);
        } else {
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

    const setFace = useCallback((name) => {
        try {
            const targetData = getFace(name);
            const queue = frameQueue.current;
            const origin = queue.length > 0
                ? queue[queue.length - 1].faceData
                : (currentFaceData.current ?? targetData);

            const steps = name.endsWith('_closed') ? BLINK_STEPS : TRANSITION_STEPS;
            for (const fd of getInBetweenFaces(origin, targetData, steps)) {
                queue.push({ faceData: fd, baseName: null });
            }
            queue.push({ faceData: targetData, baseName: name });
            currentFaceName.current = name;
        } catch (err) {
            console.warn(`[EyeRenderer] Cannot transition to "${name}":`, err.message);
        }
    }, []);

    // ── Blink ────────────────────────────────────────────────────────────────

    const scheduleBlink = useCallback(() => {
        const delay = BLINK_MIN_MS + Math.random() * (BLINK_MAX_MS - BLINK_MIN_MS);
        blinkTimer.current = setTimeout(() => {
            const name = currentFaceName.current;
            if (!name.includes('_closed')) {
                setFace(`${name}_closed`);
                setFace(name);
            }
            scheduleBlink();
        }, delay);
    }, [setFace]);

    // ── Lifecycle ─────────────────────────────────────────────────────────────

    useEffect(() => {
        const neutralData = getFace('neutral');
        currentFaceData.current = neutralData;
        renderFrame({ faceData: neutralData, baseName: 'neutral' });
        rafId.current = requestAnimationFrame(loop);
        scheduleBlink();

        return () => {
            cancelAnimationFrame(rafId.current);
            clearTimeout(blinkTimer.current);
        };
    }, [loop, renderFrame, scheduleBlink]);

    return { setFace };
}