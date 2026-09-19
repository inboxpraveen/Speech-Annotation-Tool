/* Global settings page (admin). */
(function () {
  async function load() {
    try {
      const data = await SAT.api('GET', '/api/settings');
      document.querySelectorAll('[data-key]').forEach(el => {
        const v = data.settings[el.dataset.key];
        if (el.type === 'checkbox') el.checked = !!v; else el.value = v == null ? '' : v;
      });
      const c = data.capabilities;
      const line = (k, v) => '<div class="d-flex justify-content-between border-bottom py-1"><span>' + k + '</span><span class="text-secondary">' + SAT.esc(v) + '</span></div>';
      document.getElementById('setCaps').innerHTML = line('ffmpeg', c.ffmpeg ? c.ffmpeg_version : 'missing') + line('torch', c.torch_version || 'not installed') + line('GPU', c.gpu_name || (c.torch_cuda ? 'yes' : 'none')) +
        line('faster-whisper', c.faster_whisper ? 'yes' : 'no') + line('onnx-asr', c.onnx_asr ? 'yes' : 'no') + line('transformers', c.transformers ? 'yes' : 'no') + line('qwen-asr', c.qwen_asr ? 'yes' : 'no');
    } catch (e) { SAT.toast(e.message, 'danger'); }
  }
  document.getElementById('setSave').addEventListener('click', async () => {
    const payload = {};
    document.querySelectorAll('[data-key]').forEach(el => { payload[el.dataset.key] = el.type === 'checkbox' ? el.checked : el.value; });
    try { await SAT.api('PUT', '/api/settings', payload); document.getElementById('setMsg').textContent = 'Saved at ' + new Date().toLocaleTimeString(); SAT.toast('Settings saved', 'success'); } catch (e) { SAT.toast(e.message, 'danger'); }
  });
  load();
})();
