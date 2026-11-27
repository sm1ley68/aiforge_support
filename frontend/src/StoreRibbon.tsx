import { useEffect, useRef } from 'react';

const vertexSource = `
  attribute vec2 aPosition;

  void main() {
    gl_Position = vec4(aPosition, 0.0, 1.0);
  }
`;

const fragmentSource = `
  #ifdef GL_FRAGMENT_PRECISION_HIGH
  precision highp float;
  #else
  precision mediump float;
  #endif

  uniform vec2 uSize;
  uniform float uPhase;

  float grain(vec2 p) {
    vec3 q = fract(vec3(p.xyx) * 0.1031);
    q += dot(q, q.yzx + 19.19);
    return fract((q.x + q.y) * q.z);
  }

  float falloff(float distance, float width) {
    float radius = distance / width;
    return exp(-radius * radius);
  }

  float ridge(float x, float phase) {
    float center = 0.49 + 0.106 * sin(phase + 0.15) + 0.045 * sin(2.0 * phase - 0.4);
    float bow = x - center;
    float belly = sin(clamp(x, 0.0, 1.0) * 3.14159);
    float twist = sin(x * 9.3 + 2.0 * phase + 0.55) * belly;
    return 0.286
      + 0.072 * sin(phase - 0.8)
      + (1.52 + 0.36 * sin(phase + 0.38)) * bow * bow
      + 0.118 * twist
      + 0.042 * sin(14.0 * x - 3.0 * phase) * belly
      + 0.13 * sin(phase + 1.0) * bow;
  }

  vec3 ribbonTint(float tone) {
    vec3 wine = vec3(0.36, 0.045, 0.126);
    vec3 cherry = vec3(0.65, 0.065, 0.154);
    vec3 raspberry = vec3(0.78, 0.142, 0.304);
    vec3 scarlet = vec3(0.91, 0.234, 0.272);
    vec3 coral = vec3(0.97, 0.390, 0.332);

    vec3 tint = mix(wine, cherry, smoothstep(0.0, 0.27, tone));
    tint = mix(tint, raspberry, smoothstep(0.24, 0.51, tone));
    tint = mix(tint, scarlet, smoothstep(0.49, 0.78, tone));
    return mix(tint, coral, smoothstep(0.75, 1.0, tone));
  }

  void main() {
    vec2 uv = gl_FragCoord.xy / uSize;
    uv.y = 1.0 - uv.y;
    float phase = uPhase;

    // Bend the plane across the width of the ribbon as well as along its spine.
    float x = uv.x
      + 0.067 * sin(uv.y * 7.3 + 2.0 * phase)
      + 0.039 * sin(uv.y * 12.0 - phase + uv.x * 4.0);
    float spine = ridge(x, phase);
    float slope = (ridge(x + 0.004, phase) - spine) / 0.004;
    float crossSection = (uv.y - spine) / sqrt(1.0 + 0.60 * slope * slope);

    float roll = 0.5 + 0.5 * sin(x * 8.2 + 2.0 * phase - 0.5);
    float sweep = 0.5 + 0.5 * sin(x * 5.4 - phase + 0.4);
    float centerLight = falloff(x - (0.45 + 0.18 * sin(phase + 0.2)), 0.35);
    float width = 0.036 + 0.052 * roll + 0.054 * centerLight;
    float edge = -0.023 + 0.036 * roll;
    float crest = falloff(crossSection - edge, 0.012 + 0.024 * centerLight);
    float silk = falloff(crossSection - width * 0.46, width * 0.80);
    float plume = falloff(crossSection - width * 0.86, width * 1.45);
    float penumbra = falloff(crossSection - width * 0.37, width * 2.20);
    float foldWeight = smoothstep(0.51, 0.89, roll) * (0.33 + 0.67 * centerLight);
    float fold = falloff(crossSection - width * (0.83 + 0.45 * sweep), 0.013 + 0.018 * sweep) * foldWeight;

    // The angle and twist of the ribbon drive its colour and reflected light.
    float tilt = slope / (1.0 + abs(slope));
    float exposed = 0.5 + 0.5 * sin(x * 5.8 + phase + 1.45 * roll - 1.2 * tilt);
    float temperature = smoothstep(0.09, 0.94, 0.62 * exposed + 0.38 * roll);
    vec3 body = ribbonTint(temperature);
    vec3 shadow = ribbonTint(temperature * 0.71);
    vec3 haze = mix(vec3(0.92, 0.66, 0.77), vec3(0.99, 0.79, 0.75), temperature);
    vec3 pearl = mix(vec3(0.99, 0.72, 0.83), vec3(1.0, 0.84, 0.72), temperature);
    vec3 light = mix(body, pearl, 0.53 + 0.28 * sweep);

    vec3 color = mix(vec3(1.0), haze, penumbra * 0.53);
    color = mix(color, shadow, plume * (0.53 + 0.17 * roll));
    color = mix(color, body, silk * (0.48 + 0.19 * centerLight));
    color = mix(color, light, crest * (0.58 + 0.33 * centerLight));
    color = mix(color, mix(body, pearl, sweep * 0.65), fold * 0.31);

    // The grain stays in screen space so the folds move without the texture flickering.
    float speckle = grain(floor(gl_FragCoord.xy)) - 0.5;
    float coarse = grain(floor(gl_FragCoord.xy * 0.52) + vec2(97.0, 48.0)) - 0.5;
    color += (speckle * 0.64 + coarse * 0.36) * 0.155 * penumbra;
    gl_FragColor = vec4(color, 1.0);
  }
`;

function compile(gl: WebGLRenderingContext, kind: number, source: string) {
  const shader = gl.createShader(kind);
  if (!shader) return null;
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (gl.getShaderParameter(shader, gl.COMPILE_STATUS)) return shader;
  gl.deleteShader(shader);
  return null;
}

function createRibbonRenderer(gl: WebGLRenderingContext) {
  const vertex = compile(gl, gl.VERTEX_SHADER, vertexSource);
  const fragment = compile(gl, gl.FRAGMENT_SHADER, fragmentSource);
  const program = gl.createProgram();
  const buffer = gl.createBuffer();

  if (vertex && fragment && program) {
    gl.attachShader(program, vertex);
    gl.attachShader(program, fragment);
    gl.linkProgram(program);
  }
  if (vertex) gl.deleteShader(vertex);
  if (fragment) gl.deleteShader(fragment);

  if (!vertex || !fragment || !program || !buffer || !gl.getProgramParameter(program, gl.LINK_STATUS)) {
    if (program) gl.deleteProgram(program);
    if (buffer) gl.deleteBuffer(buffer);
    return null;
  }

  gl.useProgram(program);
  gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
  const position = gl.getAttribLocation(program, 'aPosition');
  gl.enableVertexAttribArray(position);
  gl.vertexAttribPointer(position, 2, gl.FLOAT, false, 0, 0);

  const size = gl.getUniformLocation(program, 'uSize');
  const phase = gl.getUniformLocation(program, 'uPhase');

  return {
    paint(width: number, height: number, value: number) {
      gl.viewport(0, 0, width, height);
      gl.uniform2f(size, width, height);
      gl.uniform1f(phase, value);
      gl.drawArrays(gl.TRIANGLES, 0, 3);
    },
    dispose() {
      gl.deleteBuffer(buffer);
      gl.deleteProgram(program);
    },
  };
}

export function StoreRibbon() {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const gl = canvas.getContext('webgl', { alpha: false, antialias: false, depth: false, powerPreference: 'low-power' });
    if (!gl) return;

    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
    const period = 18_000;
    let renderer = createRibbonRenderer(gl);
    let frame = 0;
    let elapsed = 0;
    let previous = 0;

    function paint() {
      if (!canvas || !renderer) return;
      const phase = reducedMotion.matches ? 0.82 : elapsed * (Math.PI * 2 / period);
      renderer.paint(canvas.width, canvas.height, phase);
      canvas.dataset.ready = '';
    }

    function resize() {
      if (!canvas) return;
      const { clientWidth: width, clientHeight: height } = canvas;
      if (!width || !height) return;
      const scale = Math.min(window.devicePixelRatio || 1, 1.6, Math.sqrt(1_050_000 / (width * height)));
      canvas.width = Math.max(1, Math.round(width * scale));
      canvas.height = Math.max(1, Math.round(height * scale));
      paint();
    }

    function tick(now: number) {
      if (previous) elapsed = (elapsed + Math.min(now - previous, 64)) % period;
      previous = now;
      paint();
      frame = requestAnimationFrame(tick);
    }

    function stop() {
      cancelAnimationFrame(frame);
      frame = 0;
      previous = 0;
    }

    function syncPlayback() {
      stop();
      if (!renderer || document.hidden) return;
      if (reducedMotion.matches) {
        paint();
      } else {
        frame = requestAnimationFrame(tick);
      }
    }

    function onContextLost(event: Event) {
      event.preventDefault();
      stop();
      renderer = null;
      if (canvas) delete canvas.dataset.ready;
    }

    function onContextRestored() {
      if (!gl) return;
      renderer = createRibbonRenderer(gl);
      resize();
      syncPlayback();
    }

    const observer = new ResizeObserver(resize);
    observer.observe(canvas);
    resize();
    syncPlayback();
    document.addEventListener('visibilitychange', syncPlayback);
    reducedMotion.addEventListener('change', syncPlayback);
    canvas.addEventListener('webglcontextlost', onContextLost);
    canvas.addEventListener('webglcontextrestored', onContextRestored);

    return () => {
      stop();
      observer.disconnect();
      document.removeEventListener('visibilitychange', syncPlayback);
      reducedMotion.removeEventListener('change', syncPlayback);
      canvas.removeEventListener('webglcontextlost', onContextLost);
      canvas.removeEventListener('webglcontextrestored', onContextRestored);
      renderer?.dispose();
      delete canvas.dataset.ready;
    };
  }, []);

  return <div className="store-ribbon" aria-hidden="true"><canvas ref={canvasRef} /></div>;
}
