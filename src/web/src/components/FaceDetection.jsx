import * as blazeface from '@tensorflow-models/blazeface';
import * as tf from '@tensorflow/tfjs';
import { useEffect, useRef, useState } from 'react';
import { FACE_DETECTION_SETTINGS as settings } from '../config';
import { openInput } from '../utils/mediaInput';
import { getFaceObservation, getIntersectionOverUnion, validateFaceObservation } from './faceDetectionUtils';

let detector;
function loadDetector() {
    if (!detector) {
        detector = tf.ready().then(() => blazeface.load({
            modelUrl: '/models/blazeface/model.json',
            maxFaces: 1,
            scoreThreshold: settings.modelScoreThreshold,
        })).catch(error => {
            detector = null;
            throw error;
        });
    }
    return detector;
}

export default function FaceDetection({ active, turn, onPresence, onError }) {
    const videoRef = useRef(null);
    const latest = useRef({ turn, onPresence, onError });
    latest.current = { turn, onPresence, onError };
    const [model, setModel] = useState(null);

    useEffect(() => {
        let cancelled = false;
        loadDetector().then(loaded => {
            if (!cancelled) setModel(loaded);
        }).catch(() => {
            if (!cancelled) latest.current.onError('No se pudo cargar el detector facial.');
        });
        return () => {
            cancelled = true;
        };
    }, []);

    useEffect(() => {
        if (!model || !active) return;
        const controller = new AbortController();
        const video = videoRef.current;
        let timer;
        let watchdog;
        let lastFrame;
        let lastCheck;
        let lastSeen = Date.now();
        let reported = null;
        let samples = 0;
        let misses = 0;
        let started = 0;
        let box = null;

        const failed = () => {
            if (!controller.signal.aborted) {
                controller.abort();
                latest.current.onError('No se pudo usar la cámara. Comprueba el dispositivo y el permiso.');
            }
        };
        function watchFrames(timeout) {
            clearTimeout(watchdog);
            watchdog = setTimeout(failed, timeout);
        }
        async function detect() {
            if (controller.signal.aborted || document.hidden) return;
            const { turn: current } = latest.current;
            if (lastCheck !== current.presenceCheck) {
                lastCheck = current.presenceCheck;
                reported = null;
                samples = misses = 0;
                box = null;
                lastSeen = Date.now();
            }
            const frame = video.getVideoPlaybackQuality?.().totalVideoFrames || video.currentTime;
            if (video.readyState >= 2 && frame !== lastFrame) {
                lastFrame = frame;
                watchFrames(settings.lossTimeoutMs);
                const results = await model.estimateFaces(video, false);
                if (controller.signal.aborted) return;
                // A fresh confirmation must use frames captured after the request.
                if (latest.current.turn.turnId === current.turnId &&
                    latest.current.turn.presenceCheck === lastCheck && !document.hidden) {
                    const now = Date.now();
                    const obs = getFaceObservation(results[0]);
                    if (validateFaceObservation(obs, video, settings).valid) {
                        misses = 0;
                        lastSeen = now;
                        if (!box || getIntersectionOverUnion(box, obs) < settings.minBoxIou) {
                            started = now;
                            samples = 0;
                        }
                        box = obs;
                        samples++;
                        if (reported !== true && samples >= settings.minStableSamples &&
                            now - started >= settings.minStableDurationMs) {
                            reported = true;
                            latest.current.onPresence(true, current);
                        }
                    } else {
                        box = null;
                        samples = 0;
                        misses++;
                        if (reported !== false && misses >= settings.minConsecutiveLosses &&
                            now - lastSeen >= settings.lossTimeoutMs) {
                            reported = false;
                            latest.current.onPresence(false, current);
                        }
                    }
                }
            }
            if (!controller.signal.aborted) timer = setTimeout(() => detect().catch(failed), settings.intervalMs);
        }
        async function start() {
            watchFrames(45000);
            const stream = await openInput({ video: true, audio: false }, controller.signal);
            if (controller.signal.aborted) return;
            stream.getVideoTracks()[0].onended = failed;
            watchFrames(settings.lossTimeoutMs);
            video.srcObject = stream;
            await video.play();
            await detect();
        }
        start().catch(failed);
        return () => {
            controller.abort();
            clearTimeout(timer);
            clearTimeout(watchdog);
            video.srcObject = null;
        };
    }, [active, model]);

    return <video ref={videoRef} muted playsInline autoPlay aria-hidden="true"
        style={{ position: 'absolute', opacity: 0, pointerEvents: 'none', width: 1, height: 1 }} />;
}
