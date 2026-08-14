/**
 * Shared WebGL shader compile / program link helpers (P1-7 split).
 */

function compileShader(
  gl: WebGLRenderingContext,
  type: number,
  source: string,
  label: string,
): WebGLShader | null {
  const shader = gl.createShader(type)
  if (!shader) return null
  gl.shaderSource(shader, source)
  gl.compileShader(shader)
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    console.error(`[${label}] shader compile failed:`, gl.getShaderInfoLog(shader))
    gl.deleteShader(shader)
    return null
  }
  return shader
}

/** 链接 vertex + fragment 为 program，失败返回 null。 */
export function linkProgram(
  gl: WebGLRenderingContext,
  vertexSource: string,
  fragmentSource: string,
  label = 'WebGL',
): WebGLProgram | null {
  const vs = compileShader(gl, gl.VERTEX_SHADER, vertexSource, label)
  const fs = compileShader(gl, gl.FRAGMENT_SHADER, fragmentSource, label)
  if (!vs || !fs) {
    if (vs) gl.deleteShader(vs)
    if (fs) gl.deleteShader(fs)
    return null
  }
  const program = gl.createProgram()
  if (!program) {
    gl.deleteShader(vs)
    gl.deleteShader(fs)
    return null
  }
  gl.attachShader(program, vs)
  gl.attachShader(program, fs)
  gl.linkProgram(program)
  // 链接成功后 detach 并释放 shader 对象，减少 GPU 内存占用
  gl.detachShader(program, vs)
  gl.detachShader(program, fs)
  gl.deleteShader(vs)
  gl.deleteShader(fs)
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
    console.error(`[${label}] program link failed:`, gl.getProgramInfoLog(program))
    gl.deleteProgram(program)
    return null
  }
  return program
}
