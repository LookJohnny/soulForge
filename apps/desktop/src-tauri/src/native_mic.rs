//! Native microphone capture (cpal) → 16 kHz s16le frames → webview events.
//!
//! WKWebView on macOS never grants `getUserMedia` (wry implements no media
//! capture delegate), so the page cannot record on its own inside the desktop
//! shell. The host captures instead and hands the page 60 ms PCM frames as
//! base64 `mic-pcm` events; the page forwards them verbatim to the gateway's
//! `pcm16` listen path. TCC prompts once, attributed to the .app.

use std::sync::{Arc, Mutex};

use base64::Engine;
use cpal::traits::{DeviceTrait, HostTrait, StreamTrait};
use tauri::{AppHandle, Emitter};

const OUT_RATE: f32 = 16_000.0;
const FRAME: usize = 960; // 60 ms @ 16 kHz, same cadence as the browser paths

pub struct NativeMic {
    stream: Option<cpal::Stream>,
}

// cpal::Stream is !Send on some platforms; we only touch it from the main thread
// via Tauri's state mutex, so this is sound in practice.
unsafe impl Send for NativeMic {}

impl Default for NativeMic {
    fn default() -> Self {
        Self { stream: None }
    }
}

pub type MicState = Arc<Mutex<NativeMic>>;

#[tauri::command]
pub fn start_native_mic(app: AppHandle, window: tauri::WebviewWindow, state: tauri::State<MicState>) -> Result<String, String> {
    let mut guard = state.lock().map_err(|e| e.to_string())?;
    if guard.stream.is_some() {
        return Ok("already".into());
    }
    let host = cpal::default_host();
    let device = host
        .default_input_device()
        .ok_or_else(|| "没有可用的输入设备（系统设置 → 声音 → 输入）".to_string())?;
    let config = device.default_input_config().map_err(|e| e.to_string())?;
    let in_rate = config.sample_rate().0 as f32;
    let channels = config.channels() as usize;
    let label = window.label().to_string();
    let name = device.name().unwrap_or_else(|_| "input".into());

    // resampler state shared with the audio callback
    let ratio = in_rate / OUT_RATE;
    let mut pos = 0.0f32;
    let mut acc: Vec<i16> = Vec::with_capacity(FRAME * 2);
    let mut mono: Vec<f32> = Vec::new();

    let err_app = app.clone();
    let stream_cfg: cpal::StreamConfig = config.clone().into();
    // Build the callback for whichever sample format the device actually uses —
    // asking CoreAudio for f32 on an i16 device is the classic "unknown error".
    let mut push = move |mono_in: &[f32]| {
        mono.clear();
        for frame in mono_in.chunks(channels) {
            let s: f32 = frame.iter().sum::<f32>() / channels as f32;
            mono.push(s);
        }
        while (pos as usize) + 1 < mono.len() {
            let i = pos as usize;
            let t = pos - i as f32;
            let v = mono[i] + (mono[i + 1] - mono[i]) * t;
            acc.push((v.clamp(-1.0, 1.0) * 32767.0) as i16);
            pos += ratio;
        }
        pos -= mono.len() as f32;
        if pos < 0.0 {
            pos = 0.0;
        }
        while acc.len() >= FRAME {
            let chunk: Vec<i16> = acc.drain(..FRAME).collect();
            let bytes: Vec<u8> = chunk.iter().flat_map(|s| s.to_le_bytes()).collect();
            let b64 = base64::engine::general_purpose::STANDARD.encode(bytes);
            let _ = app.emit_to(label.as_str(), "mic-pcm", b64);
        }
    };
    let err_cb = move |e: cpal::StreamError| {
        let _ = err_app.emit("mic-error", e.to_string());
    };
    let stream = match config.sample_format() {
        cpal::SampleFormat::F32 => device.build_input_stream(
            &stream_cfg,
            move |data: &[f32], _| push(data),
            err_cb,
            None,
        ),
        cpal::SampleFormat::I16 => device.build_input_stream(
            &stream_cfg,
            move |data: &[i16], _| {
                let f: Vec<f32> = data.iter().map(|s| *s as f32 / 32768.0).collect();
                push(&f)
            },
            err_cb,
            None,
        ),
        cpal::SampleFormat::U16 => device.build_input_stream(
            &stream_cfg,
            move |data: &[u16], _| {
                let f: Vec<f32> = data.iter().map(|s| (*s as f32 - 32768.0) / 32768.0).collect();
                push(&f)
            },
            err_cb,
            None,
        ),
        other => return Err(format!("不支持的采样格式 {other:?}")),
    }
    .map_err(|e| format!("无法打开麦克风（{name} @ {in_rate:.0} Hz, {channels} ch）：{e}"))?;
    stream.play().map_err(|e| e.to_string())?;
    guard.stream = Some(stream);
    Ok(format!("{name} @ {in_rate:.0} Hz → 16 kHz PCM"))
}

#[tauri::command]
pub fn stop_native_mic(state: tauri::State<MicState>) -> Result<(), String> {
    let mut guard = state.lock().map_err(|e| e.to_string())?;
    guard.stream = None; // dropping the stream stops capture
    Ok(())
}
