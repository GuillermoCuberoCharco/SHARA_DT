import assert from 'node:assert/strict';
import test from 'node:test';

import {
    getFaceObservation,
    getIntersectionOverUnion,
    validateFaceObservation,
} from './faceDetectionUtils.js';

const settings = {
    minProbability: 0.9,
    minFaceSizePx: 96,
    minFaceSizeRatio: 0.22,
    minAspectRatio: 0.65,
    maxAspectRatio: 1.5,
};

const video = { videoWidth: 640, videoHeight: 480 };

test('normalizes BlazeFace probability arrays', () => {
    assert.deepEqual(
        getFaceObservation({
            topLeft: [200, 100],
            bottomRight: [340, 250],
            probability: [0.97],
        }),
        {
            left: 200,
            top: 100,
            right: 340,
            bottom: 250,
            width: 140,
            height: 150,
            probability: 0.97,
        },
    );
});

test('rejects the former 30px false-positive size', () => {
    const observation = getFaceObservation({
        topLeft: [100, 100],
        bottomRight: [130, 130],
        probability: [0.99],
    });

    assert.deepEqual(
        validateFaceObservation(observation, video, settings),
        { valid: false, reason: 'face_too_small' },
    );
});

test('rejects low-confidence predictions', () => {
    const observation = getFaceObservation({
        topLeft: [200, 100],
        bottomRight: [340, 250],
        probability: [0.82],
    });

    assert.deepEqual(
        validateFaceObservation(observation, video, settings),
        { valid: false, reason: 'low_probability' },
    );
});

test('accepts a high-confidence face with sufficient relative size', () => {
    const observation = getFaceObservation({
        topLeft: [200, 100],
        bottomRight: [340, 250],
        probability: [0.97],
    });

    assert.equal(validateFaceObservation(observation, video, settings).valid, true);
});

test('measures whether consecutive boxes represent the same candidate', () => {
    const first = {
        left: 100,
        top: 100,
        right: 220,
        bottom: 220,
        width: 120,
        height: 120,
    };
    const stable = { ...first, left: 105, right: 225 };
    const different = { ...first, left: 300, right: 420 };

    assert.ok(getIntersectionOverUnion(first, stable) > 0.9);
    assert.equal(getIntersectionOverUnion(first, different), 0);
});
