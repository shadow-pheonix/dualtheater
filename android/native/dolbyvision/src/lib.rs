//! Bounded RPU-only bridge. Java owns NAL framing and never passes an entire movie/frame.
use dolby_vision::rpu::{dovi_rpu::DoviRpu, rpu_data_nlq::DoviELType};
use jni::{JNIEnv, objects::{JByteArray, JClass}, sys::{jbyteArray, jint}};
use std::{panic::{catch_unwind, AssertUnwindSafe}, ptr};
const MAX_RPU: usize = 65_536;

fn parse(data: &[u8]) -> Result<DoviRpu, String> {
    if !(25..=MAX_RPU).contains(&data.len()) { return Err("Invalid RPU size".into()); }
    DoviRpu::parse_unspec62_nalu(data).map_err(|_| "Invalid RPU metadata".into())
}
fn inspect(data: &[u8]) -> Result<i32, String> {
    let rpu = parse(data)?;
    let el = match rpu.el_type { Some(DoviELType::MEL) => 1, Some(DoviELType::FEL) => 2, None => 0 };
    Ok(i32::from(rpu.dovi_profile) * 10 + el)
}
fn convert(data: &[u8]) -> Result<Vec<u8>, String> {
    let mut rpu = parse(data)?;
    if rpu.dovi_profile != 7 { return Err("Only classified Profile 7 streams may convert".into()); }
    rpu.convert_with_mode(2).map_err(|_| "RPU conversion failed")?;
    let bytes = rpu.write_hevc_unspec62_nalu().map_err(|_| "RPU serialization failed")?;
    if bytes.len() > MAX_RPU || parse(&bytes)?.dovi_profile != 8 {
        return Err("Converted RPU did not validate as Profile 8".into());
    }
    Ok(bytes)
}
fn input(env: &JNIEnv, value: &JByteArray) -> Result<Vec<u8>, String> {
    let size = env.get_array_length(value).map_err(|_| "Invalid RPU input")?;
    if !(25..=MAX_RPU as i32).contains(&size) { return Err("Invalid RPU size".into()); }
    env.convert_byte_array(value).map_err(|_| "RPU input copy failed".into())
}
#[unsafe(no_mangle)]
pub extern "system" fn Java_dev_dualtheater_tv_DolbyVisionNative_inspectRpu(
    mut env: JNIEnv, _: JClass, value: JByteArray,
) -> jint {
    let result = catch_unwind(AssertUnwindSafe(|| inspect(&input(&env, &value)?)));
    match result {
        Ok(Ok(code)) => code,
        _ => { let _ = env.throw_new("java/lang/IllegalArgumentException", "Invalid Dolby Vision RPU"); -1 }
    }
}
#[unsafe(no_mangle)]
pub extern "system" fn Java_dev_dualtheater_tv_DolbyVisionNative_convertRpu(
    mut env: JNIEnv, _: JClass, value: JByteArray,
) -> jbyteArray {
    let result = catch_unwind(AssertUnwindSafe(|| convert(&input(&env, &value)?)));
    match result {
        Ok(Ok(bytes)) => match env.byte_array_from_slice(&bytes) {
            Ok(array) => array.into_raw(),
            Err(_) => ptr::null_mut(),
        },
        _ => { let _ = env.throw_new("java/lang/IllegalArgumentException", "Dolby Vision RPU conversion failed"); ptr::null_mut() }
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    use dolby_vision::rpu::generate::GenerateConfig;
    fn p7(fel: bool) -> Vec<u8> {
        let mut rpu = DoviRpu::profile81_config(&GenerateConfig::default()).unwrap();
        rpu.convert_with_mode(1).unwrap();
        if fel { rpu.rpu_data_mapping.as_mut().unwrap().nlq.as_mut().unwrap().nlq_offset[0] = 1; }
        rpu.write_hevc_unspec62_nalu().unwrap()
    }
    #[test] fn distinguishes_mel_and_fel_from_metadata_not_container() {
        assert_eq!(inspect(&p7(false)).unwrap(), 71); assert_eq!(inspect(&p7(true)).unwrap(), 72);
    }
    #[test] fn fel_converts_and_preserves_dynamic_metadata() {
        let original = p7(true); let before = parse(&original).unwrap();
        let output = convert(&original).unwrap(); let after = parse(&output).unwrap();
        assert_eq!(inspect(&output).unwrap(), 80);
        assert!(after.header.disable_residual_flag);
        let before_dm = before.vdr_dm_data.unwrap(); let after_dm = after.vdr_dm_data.unwrap();
        assert_eq!(format!("{:?}", before_dm.cmv29_metadata), format!("{:?}", after_dm.cmv29_metadata));
        assert_eq!(format!("{:?}", before_dm.cmv40_metadata), format!("{:?}", after_dm.cmv40_metadata));
        assert_eq!(before_dm.scene_refresh_flag, after_dm.scene_refresh_flag);
        assert_eq!(before_dm.source_max_pq, after_dm.source_max_pq);
    }
    #[test] fn non_p7_is_not_converted() {
        let bytes = DoviRpu::profile81_config(&GenerateConfig::default()).unwrap().write_hevc_unspec62_nalu().unwrap();
        assert!(convert(&bytes).is_err()); assert_eq!(inspect(&bytes).unwrap(), 80);
    }
    #[test] fn malformed_and_bounded_inputs_fail_without_retry_loop() {
        for n in [0, 24, 25, 1024, MAX_RPU, MAX_RPU+1] { assert!(inspect(&vec![0; n]).is_err()); }
        let mut corrupt = p7(true); let last = corrupt.len()/2; corrupt[last] ^= 0x40;
        assert!(inspect(&corrupt).is_err());
    }
    #[test] fn emit_original_metadata_fixtures_when_requested() {
        if let Ok(directory) = std::env::var("DUALTHEATER_DOVI_FIXTURES") {
            std::fs::create_dir_all(&directory).unwrap();
            for (name, bytes) in [("p7-mel.bin",p7(false)),("p7-fel.bin",p7(true)),("p8.bin",convert(&p7(true)).unwrap())] {
                std::fs::write(std::path::Path::new(&directory).join(name), bytes).unwrap();
            }
        }
    }
}
