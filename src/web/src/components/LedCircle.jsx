/**
 * LedCircle
 *
 * Renders a circle that mirrors the physical robot's LED ring behavior.
 * Receives the robot's operational state (from state_update socket events)
 * and the pixel position/size computed by RobotView from the robot image bounds.
 *
 * State → LED mapping (mirrors leds.py from the physical robot):
 *   idle             → off          (LEDs apagados)
 *   idle_presence    → purple static (persona detectada en la sala)
 *   listening        → blue loop    (esperando que el usuario hable)
 *   recording        → white loop   (capturando voz)
 *   processing_query → off          (procesando, LEDs apagados)
 *   speaking         → blue breath  (robot hablando)
 */

import PropTypes from 'prop-types';
import '../styles/LedCircle.css';

// Colors as [R, G, B] — same values as in the physical robot's main.py
const LED_MAP = {
    idle:             { color: null,            effect: 'off'    },
    idle_presence:    { color: [186, 85,  211], effect: 'static' },
    listening:        { color: [52,  158, 235], effect: 'loop'   },
    recording:        { color: [255, 255, 255], effect: 'loop'   },
    processing_query: { color: null,            effect: 'off'    },
    speaking:         { color: [52,  158, 235], effect: 'breath' },
};

const LedCircle = ({ top, left, size, robotState = 'idle' }) => {
    const led = LED_MAP[robotState] ?? LED_MAP.idle;

    if (led.effect === 'off') return null;

    const [r, g, b] = led.color;
    const rgb = `${r}, ${g}, ${b}`;

    // Base style — transform centering is included here for static/breath.
    // For loop, the animation keyframe provides translate + rotate combined.
    const base = {
        position: 'fixed',
        top: `${top}px`,
        left: `${left}px`,
        width: `${size}px`,
        height: `${size}px`,
        borderRadius: '50%',
        transform: 'translate(-50%, -50%)',
        pointerEvents: 'none',
        zIndex: 3,
    };

    if (led.effect === 'static') {
        return (
            <div style={{
                ...base,
                backgroundColor: `rgb(${rgb})`,
                boxShadow: `0 0 12px 4px rgba(${rgb}, 0.6)`,
            }} />
        );
    }

    if (led.effect === 'breath') {
        return (
            <div
                className="led-breath"
                style={{
                    ...base,
                    backgroundColor: `rgb(${rgb})`,
                    '--led-glow': `rgba(${rgb}, 0.7)`,
                }}
            />
        );
    }

    if (led.effect === 'loop') {
        return (
            <div
                className="led-loop"
                style={{
                    ...base,
                    // conic-gradient arc (0–25%) simulates the chase/loop effect
                    background: `conic-gradient(from 0deg, transparent 0%, rgb(${rgb}) 25%, transparent 45%)`,
                }}
            />
        );
    }

    return null;
};

LedCircle.propTypes = {
    top:        PropTypes.number.isRequired,
    left:       PropTypes.number.isRequired,
    size:       PropTypes.number.isRequired,
    robotState: PropTypes.string,
};

export default LedCircle;
