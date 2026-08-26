//! Standalone cpal probe: same open sequence as native_mic.rs, prints everything.
use cpal::traits::{DeviceTrait, HostTrait, StreamTrait};
fn main() {
    let host = cpal::default_host();
    for d in host.input_devices().unwrap() {
        println!("input device: {:?}", d.name());
        if let Ok(cfgs) = d.supported_input_configs() {
            for c in cfgs { println!("  supported: {:?}", c); }
        }
    }
    let device = host.default_input_device().expect("no default input");
    let config = device.default_input_config().expect("no default config");
    println!("default: {:?} => {:?}", device.name(), config);
    let stream_cfg: cpal::StreamConfig = config.clone().into();
    let res = match config.sample_format() {
        cpal::SampleFormat::F32 => device.build_input_stream(&stream_cfg, |d: &[f32], _| { let _ = d; }, |e| eprintln!("err {e}"), None),
        cpal::SampleFormat::I16 => device.build_input_stream(&stream_cfg, |d: &[i16], _| { let _ = d; }, |e| eprintln!("err {e}"), None),
        other => { println!("format {other:?}"); return; }
    };
    match res {
        Ok(s) => { println!("stream built; play -> {:?}", s.play()); std::thread::sleep(std::time::Duration::from_millis(800)); println!("ok"); }
        Err(e) => println!("BUILD ERROR: {e}"),
    }
}
