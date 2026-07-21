/**
 * GPU wind particles for MapLibre (WebGL1 ping-pong textures).
 */

var mat4;
var $;
var map;

const WINDY_PARTICLES_DEFAULTS = {
    particleResolution: 50,
    speedScale: 60000.0,
    dropRate: 0.005,
    dropRateBump: 0.02,
    particleSize: 3.0,
    particleColor: [1.0, 1.0, 1.0, 0.8],
    trailFade: 0.96,
    windMinSpeed: 1.0,
    windMaxSpeed: 40.0,
    useTrails: true,
    particlesPerMegapixel: 700,
    speedZoom: 0,
    frameSkip: false,
    worldWrapZoom: 4,
    worldWrapSpan: 0.98
};

class WindMap {

    constructor(params = {}) {
        this.id = params.id || 'windy-particles';
        this.type = 'custom';
        this.renderingMode = '2d';

        const defaults = Object.assign({}, WINDY_PARTICLES_DEFAULTS, params);
        this.particleResolution = defaults.particleResolution;
        this.speedScale = defaults.speedScale;
        this.dropRate = defaults.dropRate;
        this.dropRateBump = defaults.dropRateBump;
        this.particleSize = defaults.particleSize;
        this.particleColor = defaults.particleColor;
        this.trailFade = defaults.trailFade;
        this.windMinSpeed = defaults.windMinSpeed;
        this.windMaxSpeed = defaults.windMaxSpeed;
        this.useTrails = defaults.useTrails;
        this.particlesPerMegapixel = defaults.particlesPerMegapixel;
        this.speedZoom = defaults.speedZoom;
        this.frameSkip = defaults.frameSkip;
        this.worldWrapZoom = defaults.worldWrapZoom;
        this.worldWrapSpan = defaults.worldWrapSpan;

        this.ready = false;
        this.visible = true;
        this.shouldSkipRendering = false;
        this.skipFrame = false;

        this.map = null;
        this.gl = null;
        this._maplibreGL = null;
        this.overlayCanvas = null;

        this.windImage = null;
        this.windTexture = null;
        this.hasWindData = false;

        this.particleCount = this.particleResolution * this.particleResolution;

        this.currentParticles = null;
        this.nextParticles = null;
        this.currentTrail = null;
        this.nextTrail = null;

        this.lastTime = 0;
        this.viewBounds = { minX: 0, minY: 0, maxX: 1, maxY: 1 };
        this.resetAll = true;
        this.density = 1.0;
        this.dragging = false;
        this._matrix = null;
        this._rafId = null;
        this._animating = false;
        this._uniformCache = { update: {}, draw: {} };
    }

    setOptions(options = {}) {
        Object.assign(this, options);
    }

    setWindImage(image) {
        this.windImage = image;
        this.windWidth = image ? image.width : 1;
        this.windHeight = image ? image.height : 1;
        this.needsWindUpload = true;
        this.hasWindData = false;
        this.resetAll = true;
        if (this.currentTrail && this.nextTrail && this.trailFBO) {
            this.clearTrail(this.currentTrail);
            this.clearTrail(this.nextTrail);
        }
        this.startAnimation();
    }

    setVisible(visible) {
        this.visible = !!visible;
        if (this.visible) {
            this.startAnimation();
        } else {
            this.clearScreen();
            if (this.currentTrail && this.nextTrail && this.trailFBO) {
                this.clearTrail(this.currentTrail);
                this.clearTrail(this.nextTrail);
            }
        }
    }

    setDragging(dragging) {
        this.dragging = !!dragging;
        if (!this.dragging && this.currentTrail) {
            this.clearTrail(this.currentTrail);
            this.clearTrail(this.nextTrail);
        }
        this.startAnimation();
    }

    setUVData() {}
    setBGData() {}
    beginRender() {
        this.startAnimation();
    }
    continueRender() {
        this.startAnimation();
    }
    initWithCanvas() {
        this.startAnimation();
    }

    startAnimation() {
        this.ready = true;
        if (!this._animating) {
            this._animating = true;
            this._rafId = requestAnimationFrame(() => this.renderFrame());
        }
    }

    handleMapChange() {
        this.updateViewBounds();
        this.resetAll = true;
        this.startAnimation();
    }

    resetContextResources() {
        this.fullscreenBuffer = null;
        this.particleIndexBuffer = null;
        this.updateProgram = null;
        this.drawProgram = null;
        this.fadeProgram = null;
        this.screenProgram = null;
        this.currentParticles = null;
        this.nextParticles = null;
        this.currentTrail = null;
        this.nextTrail = null;
        this.particleFBO = null;
        this.trailFBO = null;
        this.instancedExt = null;
        this.windTexture = null;
        this.hasWindData = false;
        this.needsWindUpload = !!this.windImage;
        this.lastTime = 0;
        this.resetAll = true;
        this._uniformCache = { update: {}, draw: {} };
    }

    onAdd(map, gl) {
        // MapLibre can re-add custom layers on setStyle without calling onRemove first.
        if (this._onResize && this.map && typeof this.map.off === 'function') {
            this.map.off('resize', this._onResize);
        }
        this._onResize = null;
        if (this._rafId) {
            cancelAnimationFrame(this._rafId);
        }
        this._rafId = null;
        this._animating = false;
        if (this.overlayCanvas && this.overlayCanvas.parentNode) {
            this.overlayCanvas.parentNode.removeChild(this.overlayCanvas);
        }
        this.overlayCanvas = null;
        this.resetContextResources();

        this.map = map;
        this._maplibreGL = gl;
        this.initOverlay();
        this.initGL();
        this.updateViewBounds();
        this.startAnimation();
    }

    onRemove() {
        this.ready = false;
        if (this._onResize) {
            this.map.off('resize', this._onResize);
        }
        if (this._rafId) {
            cancelAnimationFrame(this._rafId);
        }
        this._rafId = null;
        this._animating = false;
        if (this.overlayCanvas && this.overlayCanvas.parentNode) {
            this.overlayCanvas.parentNode.removeChild(this.overlayCanvas);
        }
        this.resetContextResources();
        this.overlayCanvas = null;
        this.map = null;
        this.gl = null;
    }

    render(gl, matrix) {
        // Just store the latest matrix and let our own RAF do the rendering.
        this._matrix = matrix || this._matrix;
        if (!this._animating) {
            this.startAnimation();
        }
    }

    renderFrame() {
        if (!this._animating) {
            return;
        }
        const gl = this.gl;
        const matrix = this._matrix;
        if (!gl || !matrix || !this.ready || !this.visible || this.shouldSkipRendering) {
            this._rafId = requestAnimationFrame(() => this.renderFrame());
            return;
        }

        if (this.frameSkip) {
            this.skipFrame = !this.skipFrame;
            if (this.skipFrame) {
                this._rafId = requestAnimationFrame(() => this.renderFrame());
                return;
            }
        }

        this.resizeOverlay();
        this.uploadWindTexture();
        this.ensureWindTexture();
        if (!this.hasWindData) {
            this.clearScreen();
            this._rafId = requestAnimationFrame(() => this.renderFrame());
            return;
        }
        this.updateDensity();
        this.updateParticles();
        this.renderTrails(matrix);

        this._rafId = requestAnimationFrame(() => this.renderFrame());
    }

    initGL() {
        const gl = this.gl;
        this.instancedExt = gl.getExtension('ANGLE_instanced_arrays');
        this.initBuffers();
        this.initPrograms();
        this.initParticles();
        this.initTrails();
    }

    initOverlay() {
        const container = this.map && this.map.getCanvasContainer ? this.map.getCanvasContainer() : null;
        if (!container) {
            // Fallback to shared GL if container is missing.
            this.gl = this._maplibreGL;
            return;
        }

        const overlay = document.createElement('canvas');
        overlay.className = 'windy-particles-overlay';
        overlay.style.position = 'absolute';
        overlay.style.left = '0';
        overlay.style.top = '0';
        overlay.style.width = '100%';
        overlay.style.height = '100%';
        overlay.style.pointerEvents = 'none';
        overlay.style.zIndex = '10';
        overlay.classList.add('leaflet-image-layer', 'leaflet-zoom-animated');
        container.appendChild(overlay);
        this.overlayCanvas = overlay;

        const overlayGL =
            overlay.getContext('webgl', { alpha: true, antialias: false, preserveDrawingBuffer: false }) ||
            overlay.getContext('experimental-webgl', { alpha: true, antialias: false, preserveDrawingBuffer: false });
        this.gl = overlayGL || this._maplibreGL;

        this._onResize = () => this.resizeOverlay(true);
        this.map.on('resize', this._onResize);
        this.resizeOverlay(true);
    }

    resizeOverlay(force) {
        if (!this.overlayCanvas || !this.map || !this.map.getCanvas) {
            return;
        }
        const mapCanvas = this.map.getCanvas();
        const width = mapCanvas.width;
        const height = mapCanvas.height;
        const cssWidth = mapCanvas.clientWidth || width;
        const cssHeight = mapCanvas.clientHeight || height;
        if (!force && this.overlayCanvas.width === width && this.overlayCanvas.height === height) {
            return;
        }
        this.overlayCanvas.width = width;
        this.overlayCanvas.height = height;
        this.overlayCanvas.style.width = `${cssWidth}px`;
        this.overlayCanvas.style.height = `${cssHeight}px`;
    }

    initBuffers() {
        const gl = this.gl;
        this.fullscreenBuffer = gl.createBuffer();
        gl.bindBuffer(gl.ARRAY_BUFFER, this.fullscreenBuffer);
        gl.bufferData(
            gl.ARRAY_BUFFER,
            new Float32Array([
                -1, -1, 0, 0,
                 1, -1, 1, 0,
                -1,  1, 0, 1,
                -1,  1, 0, 1,
                 1, -1, 1, 0,
                 1,  1, 1, 1
            ]),
            gl.STATIC_DRAW
        );

        const texCoords = new Float32Array(this.particleCount * 2);
        let idx = 0;
        for (let y = 0; y < this.particleResolution; y++) {
            for (let x = 0; x < this.particleResolution; x++) {
                texCoords[idx++] = (x + 0.5) / this.particleResolution;
                texCoords[idx++] = (y + 0.5) / this.particleResolution;
            }
        }
        this.particleIndexBuffer = gl.createBuffer();
        gl.bindBuffer(gl.ARRAY_BUFFER, this.particleIndexBuffer);
        gl.bufferData(gl.ARRAY_BUFFER, texCoords, gl.STATIC_DRAW);
    }

    initPrograms() {
        const gl = this.gl;
        this.updateProgram = this.createProgram(this.updateVertexShader(), this.updateFragmentShader());
        this.updateProgram.a_pos = gl.getAttribLocation(this.updateProgram.program, 'a_pos');
        this.updateProgram.a_uv = gl.getAttribLocation(this.updateProgram.program, 'a_uv');
        this.updateProgram.u_particles = gl.getUniformLocation(this.updateProgram.program, 'u_particles');
        this.updateProgram.u_wind = gl.getUniformLocation(this.updateProgram.program, 'u_wind');
        this.updateProgram.u_speed_factor = gl.getUniformLocation(this.updateProgram.program, 'u_speed_factor');
        this.updateProgram.u_drop_rate = gl.getUniformLocation(this.updateProgram.program, 'u_drop_rate');
        this.updateProgram.u_drop_rate_bump = gl.getUniformLocation(this.updateProgram.program, 'u_drop_rate_bump');
        this.updateProgram.u_rand_seed = gl.getUniformLocation(this.updateProgram.program, 'u_rand_seed');
        this.updateProgram.u_speed_range = gl.getUniformLocation(this.updateProgram.program, 'u_speed_range');
        this.updateProgram.u_wind_res = gl.getUniformLocation(this.updateProgram.program, 'u_wind_res');
        this.updateProgram.u_view_bounds = gl.getUniformLocation(this.updateProgram.program, 'u_view_bounds');
        this.updateProgram.u_reset_all = gl.getUniformLocation(this.updateProgram.program, 'u_reset_all');

        this.drawProgram = this.createProgram(this.drawVertexShader(), this.drawFragmentShader());
        this.drawProgram.a_tex_pos = gl.getAttribLocation(this.drawProgram.program, 'a_tex_pos');
        this.drawProgram.u_particles = gl.getUniformLocation(this.drawProgram.program, 'u_particles');
        this.drawProgram.u_matrix = gl.getUniformLocation(this.drawProgram.program, 'u_matrix');
        this.drawProgram.u_point_size = gl.getUniformLocation(this.drawProgram.program, 'u_point_size');
        this.drawProgram.u_wind = gl.getUniformLocation(this.drawProgram.program, 'u_wind');
        this.drawProgram.u_color = gl.getUniformLocation(this.drawProgram.program, 'u_color');
        this.drawProgram.u_speed_range = gl.getUniformLocation(this.drawProgram.program, 'u_speed_range');
        this.drawProgram.u_view_bounds = gl.getUniformLocation(this.drawProgram.program, 'u_view_bounds');
        this.drawProgram.u_density = gl.getUniformLocation(this.drawProgram.program, 'u_density');

        this.fadeProgram = this.createProgram(this.fadeVertexShader(), this.fadeFragmentShader());
        this.fadeProgram.a_pos = gl.getAttribLocation(this.fadeProgram.program, 'a_pos');
        this.fadeProgram.a_uv = gl.getAttribLocation(this.fadeProgram.program, 'a_uv');
        this.fadeProgram.u_texture = gl.getUniformLocation(this.fadeProgram.program, 'u_texture');
        this.fadeProgram.u_fade = gl.getUniformLocation(this.fadeProgram.program, 'u_fade');

        this.screenProgram = this.createProgram(this.screenVertexShader(), this.screenFragmentShader());
        this.screenProgram.a_pos = gl.getAttribLocation(this.screenProgram.program, 'a_pos');
        this.screenProgram.a_uv = gl.getAttribLocation(this.screenProgram.program, 'a_uv');
        this.screenProgram.u_texture = gl.getUniformLocation(this.screenProgram.program, 'u_texture');
    }

    initParticles() {
        const gl = this.gl;
        this.currentParticles = this.createParticleState();
        this.nextParticles = this.createParticleState();
        this.particleFBO = gl.createFramebuffer();
    }

    initTrails() {
        const gl = this.gl;
        const canvas = this.map.getCanvas();
        const width = canvas.width;
        const height = canvas.height;
        this.currentTrail = this.createColorTarget(width, height);
        this.nextTrail = this.createColorTarget(width, height);
        this.trailFBO = gl.createFramebuffer();
        this.clearTrail(this.currentTrail);
        this.clearTrail(this.nextTrail);
    }

    uploadWindTexture() {
        if (!this.needsWindUpload || !this.windImage) {
            return;
        }
        if (this.windImage.complete !== true ||
            !this.windImage.naturalWidth ||
            !this.windImage.naturalHeight) {
            return;
        }
        const gl = this.gl;
        const prevPremultiply = gl.getParameter(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL);
        const prevFlipY = gl.getParameter(gl.UNPACK_FLIP_Y_WEBGL);
        if (!this.windTexture) {
            this.windTexture = gl.createTexture();
            gl.bindTexture(gl.TEXTURE_2D, this.windTexture);
            gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
            gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
            gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
            gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
        }
        gl.bindTexture(gl.TEXTURE_2D, this.windTexture);
        gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false);
        gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
        gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, this.windImage);
        gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, prevPremultiply);
        gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, prevFlipY);
        this.needsWindUpload = false;
        this.hasWindData = true;
    }

    ensureWindTexture() {
        if (this.windTexture) {
            return;
        }
        const gl = this.gl;
        this.windTexture = gl.createTexture();
        this.windWidth = 1;
        this.windHeight = 1;
        gl.bindTexture(gl.TEXTURE_2D, this.windTexture);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
        gl.texImage2D(
            gl.TEXTURE_2D,
            0,
            gl.RGBA,
            1,
            1,
            0,
            gl.RGBA,
            gl.UNSIGNED_BYTE,
            new Uint8Array([128, 128, 0, 255])
        );
    }

    updateParticles() {
        const gl = this.gl;
        const now = performance.now();
        const delta = this.lastTime ? Math.min(50, now - this.lastTime) : 16.7;
        this.lastTime = now;

        const seedX = Math.random();
        const seedY = Math.random();
        const view = this.viewBounds;
        const resetAll = this.resetAll ? 1.0 : 0.0;

        gl.useProgram(this.updateProgram.program);
        gl.bindFramebuffer(gl.FRAMEBUFFER, this.particleFBO);
        gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, this.nextParticles.texture, 0);
        gl.viewport(0, 0, this.particleResolution, this.particleResolution);
        gl.disable(gl.DEPTH_TEST);
        gl.depthMask(false);
        gl.disable(gl.BLEND);

        this.bindFullscreen(this.updateProgram, gl);

        gl.activeTexture(gl.TEXTURE0);
        gl.bindTexture(gl.TEXTURE_2D, this.currentParticles.texture);
        gl.uniform1i(this.updateProgram.u_particles, 0);

        gl.activeTexture(gl.TEXTURE1);
        gl.bindTexture(gl.TEXTURE_2D, this.windTexture);
        gl.uniform1i(this.updateProgram.u_wind, 1);

        const spanX = view.maxX - view.minX;
        const spanY = view.maxY - view.minY;
        const span = Math.max(spanX, spanY);
        const speedFactor = (delta / 1000) * this.speedScale * span;
        this.setUniform1fCached(gl, this._uniformCache.update, 'u_speed_factor', this.updateProgram.u_speed_factor, speedFactor);
        this.setUniform1fCached(gl, this._uniformCache.update, 'u_drop_rate', this.updateProgram.u_drop_rate, this.dropRate);
        this.setUniform1fCached(gl, this._uniformCache.update, 'u_drop_rate_bump', this.updateProgram.u_drop_rate_bump, this.dropRateBump);
        gl.uniform2f(this.updateProgram.u_rand_seed, seedX, seedY);
        this.setUniform2fCached(gl, this._uniformCache.update, 'u_speed_range', this.updateProgram.u_speed_range, this.windMinSpeed, this.windMaxSpeed);
        this.setUniform2fCached(gl, this._uniformCache.update, 'u_wind_res', this.updateProgram.u_wind_res, this.windWidth || 1, this.windHeight || 1);
        this.setUniform4fCached(gl, this._uniformCache.update, 'u_view_bounds', this.updateProgram.u_view_bounds, view.minX, view.minY, view.maxX, view.maxY);
        this.setUniform1fCached(gl, this._uniformCache.update, 'u_reset_all', this.updateProgram.u_reset_all, resetAll);

        gl.drawArrays(gl.TRIANGLES, 0, 6);

        gl.bindFramebuffer(gl.FRAMEBUFFER, null);
        this.swapParticles();
        this.resetAll = false;
    }

    renderTrails(matrix) {
        const gl = this.gl;
        const canvas = this.map.getCanvas();
        const width = canvas.width;
        const height = canvas.height;

        if (!this.useTrails || this.dragging) {
            gl.bindFramebuffer(gl.FRAMEBUFFER, null);
            gl.viewport(0, 0, width, height);
            gl.useProgram(this.drawProgram.program);
            gl.bindBuffer(gl.ARRAY_BUFFER, this.particleIndexBuffer);
            gl.enableVertexAttribArray(this.drawProgram.a_tex_pos);
            gl.vertexAttribPointer(this.drawProgram.a_tex_pos, 2, gl.FLOAT, false, 0, 0);
            if (this.instancedExt) {
                this.instancedExt.vertexAttribDivisorANGLE(this.drawProgram.a_tex_pos, 0);
            }

            gl.activeTexture(gl.TEXTURE0);
            gl.bindTexture(gl.TEXTURE_2D, this.currentParticles.texture);
            gl.uniform1i(this.drawProgram.u_particles, 0);

            gl.activeTexture(gl.TEXTURE1);
            gl.bindTexture(gl.TEXTURE_2D, this.windTexture);
            gl.uniform1i(this.drawProgram.u_wind, 1);

            gl.uniformMatrix4fv(this.drawProgram.u_matrix, false, matrix);
            gl.uniform1f(this.drawProgram.u_point_size, this.particleSize);
            gl.uniform4f(
                this.drawProgram.u_color,
                this.particleColor[0],
                this.particleColor[1],
                this.particleColor[2],
                this.particleColor[3]
            );
            this.setUniform2fCached(gl, this._uniformCache.draw, 'u_speed_range', this.drawProgram.u_speed_range, this.windMinSpeed, this.windMaxSpeed);
            this.setUniform4fCached(gl, this._uniformCache.draw, 'u_view_bounds', this.drawProgram.u_view_bounds, this.viewBounds.minX, this.viewBounds.minY, this.viewBounds.maxX, this.viewBounds.maxY);
            this.setUniform1fCached(gl, this._uniformCache.draw, 'u_density', this.drawProgram.u_density, this.density);

            gl.enable(gl.BLEND);
            gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
            gl.blendEquation(gl.FUNC_ADD);
            const dx = matrix[0];
            const wrap = this.shouldWorldWrap();
            const start = wrap ? -1 : 0;
            const end = wrap ? 1 : 0;
            for (let i = start; i <= end; i++) {
                const m = matrix.slice();
                m[12] += i * dx;
                gl.uniformMatrix4fv(this.drawProgram.u_matrix, false, m);
                gl.drawArrays(gl.POINTS, 0, this.particleCount);
            }
            return;
        }

        if (this.currentTrail.width !== width || this.currentTrail.height !== height) {
            this.currentTrail = this.createColorTarget(width, height);
            this.nextTrail = this.createColorTarget(width, height);
            this.clearTrail(this.currentTrail);
            this.clearTrail(this.nextTrail);
        }

        gl.bindFramebuffer(gl.FRAMEBUFFER, this.trailFBO);
        gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, this.nextTrail.texture, 0);
        gl.viewport(0, 0, width, height);

        gl.useProgram(this.fadeProgram.program);
        this.bindFullscreen(this.fadeProgram, gl);
        gl.disable(gl.BLEND);
        gl.activeTexture(gl.TEXTURE0);
        gl.bindTexture(gl.TEXTURE_2D, this.currentTrail.texture);
        gl.uniform1i(this.fadeProgram.u_texture, 0);
        gl.uniform1f(this.fadeProgram.u_fade, this.trailFade);
        gl.drawArrays(gl.TRIANGLES, 0, 6);

        gl.useProgram(this.drawProgram.program);
        gl.bindBuffer(gl.ARRAY_BUFFER, this.particleIndexBuffer);
        gl.enableVertexAttribArray(this.drawProgram.a_tex_pos);
        gl.vertexAttribPointer(this.drawProgram.a_tex_pos, 2, gl.FLOAT, false, 0, 0);
        if (this.instancedExt) {
            this.instancedExt.vertexAttribDivisorANGLE(this.drawProgram.a_tex_pos, 0);
        }
        gl.disable(gl.DEPTH_TEST);
        gl.depthMask(false);

        gl.activeTexture(gl.TEXTURE0);
        gl.bindTexture(gl.TEXTURE_2D, this.currentParticles.texture);
        gl.uniform1i(this.drawProgram.u_particles, 0);

        gl.activeTexture(gl.TEXTURE1);
        gl.bindTexture(gl.TEXTURE_2D, this.windTexture);
        gl.uniform1i(this.drawProgram.u_wind, 1);

        gl.uniform1f(this.drawProgram.u_point_size, this.particleSize);
        gl.uniform4f(
            this.drawProgram.u_color,
            this.particleColor[0],
            this.particleColor[1],
            this.particleColor[2],
            this.particleColor[3]
        );
        this.setUniform2fCached(gl, this._uniformCache.draw, 'u_speed_range', this.drawProgram.u_speed_range, this.windMinSpeed, this.windMaxSpeed);
        this.setUniform4fCached(gl, this._uniformCache.draw, 'u_view_bounds', this.drawProgram.u_view_bounds, this.viewBounds.minX, this.viewBounds.minY, this.viewBounds.maxX, this.viewBounds.maxY);
        this.setUniform1fCached(gl, this._uniformCache.draw, 'u_density', this.drawProgram.u_density, this.density);

        gl.enable(gl.BLEND);
        gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
        gl.blendEquation(gl.FUNC_ADD);
        const dx = matrix[0];
        const wrap = this.shouldWorldWrap();
        const start = wrap ? -1 : 0;
        const end = wrap ? 1 : 0;
        for (let i = start; i <= end; i++) {
            const m = matrix.slice();
            m[12] += i * dx;
            gl.uniformMatrix4fv(this.drawProgram.u_matrix, false, m);
            gl.drawArrays(gl.POINTS, 0, this.particleCount);
        }
        gl.bindFramebuffer(gl.FRAMEBUFFER, null);

        gl.viewport(0, 0, width, height);
        gl.useProgram(this.screenProgram.program);
        this.bindFullscreen(this.screenProgram, gl);
        gl.activeTexture(gl.TEXTURE0);
        gl.bindTexture(gl.TEXTURE_2D, this.nextTrail.texture);
        gl.uniform1i(this.screenProgram.u_texture, 0);
        gl.enable(gl.BLEND);
        gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
        gl.blendEquation(gl.FUNC_ADD);
        gl.drawArrays(gl.TRIANGLES, 0, 6);

        this.swapTrails();
    }

    bindFullscreen(program, gl) {
        gl.bindBuffer(gl.ARRAY_BUFFER, this.fullscreenBuffer);
        gl.enableVertexAttribArray(program.a_pos);
        gl.vertexAttribPointer(program.a_pos, 2, gl.FLOAT, false, 16, 0);
        gl.enableVertexAttribArray(program.a_uv);
        gl.vertexAttribPointer(program.a_uv, 2, gl.FLOAT, false, 16, 8);
        if (this.instancedExt) {
            this.instancedExt.vertexAttribDivisorANGLE(program.a_pos, 0);
            this.instancedExt.vertexAttribDivisorANGLE(program.a_uv, 0);
        }
    }

    createParticleState() {
        const gl = this.gl;
        const data = new Uint8Array(this.particleResolution * this.particleResolution * 4);
        let idx = 0;
        for (let i = 0; i < this.particleResolution * this.particleResolution; i++) {
            const x = Math.random();
            const y = Math.random();
            const enc = this.encodePosition(x, y);
            data[idx++] = enc[0];
            data[idx++] = enc[1];
            data[idx++] = enc[2];
            data[idx++] = enc[3];
        }
        const texture = gl.createTexture();
        gl.bindTexture(gl.TEXTURE_2D, texture);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
        gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, this.particleResolution, this.particleResolution, 0, gl.RGBA, gl.UNSIGNED_BYTE, data);
        return { texture };
    }


    createColorTarget(width, height) {
        const gl = this.gl;
        const texture = gl.createTexture();
        gl.bindTexture(gl.TEXTURE_2D, texture);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
        gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, width, height, 0, gl.RGBA, gl.UNSIGNED_BYTE, null);
        return { texture, width, height };
    }

    clearTrail(target) {
        const gl = this.gl;
        gl.bindFramebuffer(gl.FRAMEBUFFER, this.trailFBO);
        gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, target.texture, 0);
        gl.viewport(0, 0, target.width, target.height);
        gl.clearColor(0, 0, 0, 0);
        gl.clear(gl.COLOR_BUFFER_BIT);
        gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    }

    clearScreen() {
        if (!this.gl || !this.map || !this.map.getCanvas) return;
        const gl = this.gl;
        const canvas = this.map.getCanvas();
        gl.bindFramebuffer(gl.FRAMEBUFFER, null);
        gl.viewport(0, 0, canvas.width, canvas.height);
        gl.clearColor(0, 0, 0, 0);
        gl.clear(gl.COLOR_BUFFER_BIT);
    }

    swapParticles() {
        const tmp = this.currentParticles;
        this.currentParticles = this.nextParticles;
        this.nextParticles = tmp;
    }

    swapTrails() {
        const tmp = this.currentTrail;
        this.currentTrail = this.nextTrail;
        this.nextTrail = tmp;
    }

    captureGLState() {
        return null;
    }

    restoreGLState(state) {
        return;
    }

    encodePosition(x, y) {
        const xr = Math.floor(x * 255);
        const yr = Math.floor(y * 255);
        const xf = Math.round((x * 255 - xr) * 255);
        const yf = Math.round((y * 255 - yr) * 255);
        return [xf, yf, xr, yr];
    }

    updateViewBounds() {
        if (!this.map || !this.map.getBounds) {
            this.viewBounds = { minX: 0, minY: 0, maxX: 1, maxY: 1 };
            return;
        }
        const bounds = this.map.getBounds();
        const sw = bounds.getSouthWest();
        const ne = bounds.getNorthEast();
        let minLng = sw.lng;
        let maxLng = ne.lng;
        const center = this.map.getCenter ? this.map.getCenter() : null;
        const centerLng = center ? center.lng : 0;
        if (centerLng > 180) {
            minLng -= 360;
            maxLng -= 360;
        } else if (centerLng < -180) {
            minLng += 360;
            maxLng += 360;
        }
        if (minLng > maxLng) {
            this.viewBounds = { minX: 0, minY: 0, maxX: 1, maxY: 1 };
            return;
        }
        const minLat = Math.max(-90, Math.min(90, sw.lat));
        const maxLat = Math.max(-90, Math.min(90, ne.lat));
        const minX = (minLng + 180) / 360;
        const maxX = (maxLng + 180) / 360;
        const minY = (minLat + 90) / 180;
        const maxY = (maxLat + 90) / 180;
        this.viewBounds = {
            minX: Math.min(minX, maxX),
            maxX: Math.max(minX, maxX),
            minY: Math.min(minY, maxY),
            maxY: Math.max(minY, maxY)
        };
    }

    updateDensity() {
        if (!this.map || !this.map.getCanvas) {
            this.density = 1.0;
            return;
        }
        const canvas = this.map.getCanvas();
        const pixels = canvas.width * canvas.height;
        const target = Math.round((pixels / 1000000) * this.particlesPerMegapixel);
        const spanX = this.viewBounds.maxX - this.viewBounds.minX;
        const spanY = this.viewBounds.maxY - this.viewBounds.minY;
        const span = Math.max(0.0, Math.min(1.0, Math.max(spanX, spanY)));
        const spanFactor = Math.sqrt(span);
        this.density = Math.max(0.0, Math.min(1.0, (target / this.particleCount) * spanFactor));
    }

    shouldWorldWrap() {
        if (!this.map || typeof this.map.getBounds !== 'function') {
            return false;
        }
        if (this.map.getRenderWorldCopies && !this.map.getRenderWorldCopies()) {
            return false;
        }
        if (this.map.getCenter && this.map.getCanvas && this.map.transform && this.map.transform.worldSize) {
            const center = this.map.getCenter();
            const canvas = this.map.getCanvas();
            const worldSize = this.map.transform.worldSize;
            const halfSpanDeg = (canvas.width * 360) / worldSize / 2;
            const lng = center && typeof center.lng === 'number' ? center.lng : 0;
            if (lng - halfSpanDeg < -180 || lng + halfSpanDeg > 180) {
                return true;
            }
        }
        const b = this.map.getBounds();
        const west = b.getWest();
        const east = b.getEast();
        if (west > east) {
            return true; // пересечение антимередиана
        }
        const spanLng = east - west;
        if (spanLng >= 360 * this.worldWrapSpan) {
            return true; // почти весь мир в кадре
        }
        return false;
    }

    setUniform1fCached(gl, cache, key, loc, value) {
        if (cache[key] === value) return;
        gl.uniform1f(loc, value);
        cache[key] = value;
    }

    setUniform2fCached(gl, cache, key, loc, a, b) {
        const prev = cache[key];
        if (prev && prev[0] === a && prev[1] === b) return;
        gl.uniform2f(loc, a, b);
        cache[key] = [a, b];
    }

    setUniform4fCached(gl, cache, key, loc, a, b, c, d) {
        const prev = cache[key];
        if (prev && prev[0] === a && prev[1] === b && prev[2] === c && prev[3] === d) return;
        gl.uniform4f(loc, a, b, c, d);
        cache[key] = [a, b, c, d];
    }

    createProgram(vertexSrc, fragmentSrc) {
        const gl = this.gl;
        const vs = this.createShader(vertexSrc, gl.VERTEX_SHADER);
        const fs = this.createShader(fragmentSrc, gl.FRAGMENT_SHADER);
        const program = gl.createProgram();
        gl.attachShader(program, vs);
        gl.attachShader(program, fs);
        gl.linkProgram(program);
        return { program, vs, fs };
    }

    createShader(source, type) {
        const gl = this.gl;
        const shader = gl.createShader(type);
        gl.shaderSource(shader, source);
        gl.compileShader(shader);
        return shader;
    }

    updateVertexShader() {
        return `
            attribute vec2 a_pos;
            attribute vec2 a_uv;
            varying vec2 v_tex_pos;
            void main() {
                v_tex_pos = a_uv;
                gl_Position = vec4(a_pos, 0.0, 1.0);
            }
        `;
    }

    updateFragmentShader() {
        return `
            precision highp float;
            varying vec2 v_tex_pos;
            uniform sampler2D u_particles;
            uniform sampler2D u_wind;
            uniform float u_speed_factor;
            uniform float u_drop_rate;
            uniform float u_drop_rate_bump;
            uniform vec2 u_rand_seed;
            uniform vec2 u_speed_range;
            uniform vec2 u_wind_res;
            uniform vec4 u_view_bounds;
            uniform float u_reset_all;

            float rand(vec2 co) {
                return fract(sin(dot(co, vec2(12.9898, 78.233))) * 43758.5453);
            }

            vec2 decodePos(vec4 c) {
                return vec2(c.b + c.r / 255.0, c.a + c.g / 255.0);
            }

            vec2 windToVector(vec4 wind) {
                float speed = mix(u_speed_range.x, u_speed_range.y, wind.r);
                float dir = wind.g * 6.2831853;
                return vec2(speed * sin(dir) * -1.0, speed * cos(dir) * -1.0);
            }

            vec3 sampleWind(vec2 uv) {
                vec2 res = max(u_wind_res, vec2(1.0));
                vec2 texel = 1.0 / res;
                vec2 pixel = uv * res - 0.5;
                vec2 base = floor(pixel);
                vec2 f = fract(pixel);
                vec2 uv00 = (base + vec2(0.5, 0.5)) * texel;
                vec2 uv10 = (base + vec2(1.5, 0.5)) * texel;
                vec2 uv01 = (base + vec2(0.5, 1.5)) * texel;
                vec2 uv11 = (base + vec2(1.5, 1.5)) * texel;
                uv00 = clamp(uv00, vec2(0.0), vec2(1.0));
                uv10 = clamp(uv10, vec2(0.0), vec2(1.0));
                uv01 = clamp(uv01, vec2(0.0), vec2(1.0));
                uv11 = clamp(uv11, vec2(0.0), vec2(1.0));
                vec4 w00 = texture2D(u_wind, uv00);
                vec4 w10 = texture2D(u_wind, uv10);
                vec4 w01 = texture2D(u_wind, uv01);
                vec4 w11 = texture2D(u_wind, uv11);
                vec2 v00 = windToVector(w00);
                vec2 v10 = windToVector(w10);
                vec2 v01 = windToVector(w01);
                vec2 v11 = windToVector(w11);
                vec2 v0 = mix(v00, v10, f.x);
                vec2 v1 = mix(v01, v11, f.x);
                float a0 = mix(w00.a, w10.a, f.x);
                float a1 = mix(w01.a, w11.a, f.x);
                float a = mix(a0, a1, f.y);
                return vec3(mix(v0, v1, f.y), a);
            }

            vec4 encodePos(vec2 pos) {
                vec2 enc = fract(pos * 255.0);
                vec2 high = floor(pos * 255.0) / 255.0;
                return vec4(enc.x, enc.y, high.x, high.y);
            }

            void main() {
                vec4 state = texture2D(u_particles, v_tex_pos);
                vec2 pos = decodePos(state);
                vec2 globalPos = vec2(
                    mix(u_view_bounds.x, u_view_bounds.z, pos.x),
                    mix(u_view_bounds.y, u_view_bounds.w, pos.y)
                );
                vec2 windUV = vec2(fract(globalPos.x), 1.0 - globalPos.y);
                vec3 flowA = sampleWind(windUV);
                vec2 flow = flowA.xy;
                float dataAlpha = flowA.z;
                float speed = length(flow);
                float u = flow.x;
                float v = flow.y;

                float lat = mix(-90.0, 90.0, globalPos.y);
                lat = clamp(lat, -85.0, 85.0);
                float metersPerDegLon = 111320.0 * cos(radians(lat));
                float metersPerDegLat = 111320.0;
                vec2 deg = vec2(u / metersPerDegLon, v / metersPerDegLat);
                vec2 normalized = vec2(deg.x / 360.0, deg.y / 180.0);
                float mercatorScale = cos(radians(lat));
                normalized *= mercatorScale;

                globalPos += normalized * u_speed_factor;
                pos = vec2(
                    (globalPos.x - u_view_bounds.x) / max(1e-6, (u_view_bounds.z - u_view_bounds.x)),
                    (globalPos.y - u_view_bounds.y) / max(1e-6, (u_view_bounds.w - u_view_bounds.y))
                );

                bool outBounds = pos.x < 0.0 || pos.x > 1.0 || pos.y < 0.0 || pos.y > 1.0;
                bool noData = dataAlpha < 0.01;
                float speedT = clamp(speed / u_speed_range.y, 0.0, 1.0);
                float drop = u_drop_rate + speedT * u_drop_rate_bump;
                vec2 seed = v_tex_pos + u_rand_seed;
                bool lowWind = false;
                if (u_reset_all > 0.5 || outBounds || noData || lowWind || rand(seed) < drop) {
                    pos = vec2(rand(seed + vec2(1.3, 2.1)), rand(seed + vec2(2.7, 4.3)));
                }

                gl_FragColor = encodePos(pos);
            }
        `;
    }

    drawVertexShader() {
        return `
            precision highp float;
            attribute vec2 a_tex_pos;
            uniform sampler2D u_particles;
            uniform mat4 u_matrix;
            uniform float u_point_size;
            uniform vec4 u_view_bounds;
            varying vec2 v_pos;
            varying vec2 v_tex_pos;

            vec2 decodePos(vec4 c) {
                return vec2(c.b + c.r / 255.0, c.a + c.g / 255.0);
            }

            void main() {
                vec4 state = texture2D(u_particles, a_tex_pos);
                vec2 pos = decodePos(state);
                vec2 globalPos = vec2(
                    mix(u_view_bounds.x, u_view_bounds.z, pos.x),
                    mix(u_view_bounds.y, u_view_bounds.w, pos.y)
                );
                v_pos = vec2(fract(globalPos.x), globalPos.y);
                v_tex_pos = a_tex_pos;

                float lon = mix(-180.0, 180.0, fract(globalPos.x));
                float lat = mix(-90.0, 90.0, globalPos.y);
                lat = clamp(lat, -85.0, 85.0);
                float sinLat = sin(radians(lat));
                float mercY = 0.5 - log((1.0 + sinLat) / (1.0 - sinLat)) / (4.0 * 3.14159265);
                float mercX = (lon + 180.0) / 360.0;

                gl_Position = u_matrix * vec4(mercX, mercY, 0.0, 1.0);
                gl_PointSize = u_point_size;
            }
        `;
    }

    drawFragmentShader() {
        return `
            precision mediump float;
            uniform sampler2D u_wind;
            uniform vec4 u_color;
            uniform vec2 u_speed_range;
            varying vec2 v_pos;
            varying vec2 v_tex_pos;
            uniform float u_density;

            float rand(vec2 co) {
                return fract(sin(dot(co, vec2(12.9898, 78.233))) * 43758.5453);
            }

            void main() {
                float mask = rand(v_tex_pos * 4096.0);
                if (mask > u_density) {
                    discard;
                }
                vec2 windUV = vec2(v_pos.x, 1.0 - v_pos.y);
                vec4 wind = texture2D(u_wind, windUV);
                if (wind.a < 0.01) {
                    discard;
                }
                float speed = mix(u_speed_range.x, u_speed_range.y, wind.r);
                float alpha = u_color.a;
                if (speed <= 0.0) {
                    alpha = 0.0;
                }
                gl_FragColor = vec4(u_color.rgb, alpha);
            }
        `;
    }

    fadeVertexShader() {
        return `
            attribute vec2 a_pos;
            attribute vec2 a_uv;
            varying vec2 v_uv;
            void main() {
                v_uv = a_uv;
                gl_Position = vec4(a_pos, 0.0, 1.0);
            }
        `;
    }

    fadeFragmentShader() {
        return `
            precision mediump float;
            varying vec2 v_uv;
            uniform sampler2D u_texture;
            uniform float u_fade;
            void main() {
                vec4 color = texture2D(u_texture, v_uv);
                gl_FragColor = vec4(color.rgb * u_fade, color.a * u_fade);
            }
        `;
    }

    screenVertexShader() {
        return this.fadeVertexShader();
    }

    screenFragmentShader() {
        return `
            precision mediump float;
            varying vec2 v_uv;
            uniform sampler2D u_texture;
            void main() {
                gl_FragColor = texture2D(u_texture, v_uv);
            }
        `;
    }
}

window.WindMap = WindMap;
window.WINDY_PARTICLES_DEFAULTS = WINDY_PARTICLES_DEFAULTS;
