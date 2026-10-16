//! Same-user native authentication, independent of which process started the backend.
use base64::Engine;
use std::{fs, io::Write, path::Path};

#[cfg(windows)]
fn protect(bytes: &[u8], encrypt: bool) -> Result<Vec<u8>, String> {
    use windows_sys::Win32::{
        Foundation::LocalFree,
        Security::Cryptography::{
            CryptProtectData, CryptUnprotectData, CRYPTPROTECT_UI_FORBIDDEN, CRYPT_INTEGER_BLOB,
        },
    };
    let input = CRYPT_INTEGER_BLOB {
        cbData: bytes.len() as u32,
        pbData: bytes.as_ptr() as *mut u8,
    };
    let mut output = CRYPT_INTEGER_BLOB {
        cbData: 0,
        pbData: std::ptr::null_mut(),
    };
    // DPAPI's default scope is the current OS user, never the whole machine.
    let ok = unsafe {
        if encrypt {
            CryptProtectData(
                &input,
                std::ptr::null(),
                std::ptr::null(),
                std::ptr::null(),
                std::ptr::null(),
                CRYPTPROTECT_UI_FORBIDDEN,
                &mut output,
            )
        } else {
            CryptUnprotectData(
                &input,
                std::ptr::null_mut(),
                std::ptr::null(),
                std::ptr::null(),
                std::ptr::null(),
                CRYPTPROTECT_UI_FORBIDDEN,
                &mut output,
            )
        }
    };
    if ok == 0 {
        return Err("desktop_account_credential_unavailable".into());
    }
    let result =
        unsafe { std::slice::from_raw_parts(output.pbData, output.cbData as usize).to_vec() };
    unsafe {
        LocalFree(output.pbData.cast());
    }
    Ok(result)
}

fn decode(bytes: Vec<u8>) -> Result<String, String> {
    #[cfg(windows)]
    let bytes = protect(
        bytes
            .strip_prefix(b"OAKDPAPI1\0")
            .ok_or("desktop_account_credential_invalid")?,
        false,
    )?;
    let token = String::from_utf8(bytes).map_err(|_| "desktop_account_credential_invalid")?;
    if token.len() != 43
        || !token
            .bytes()
            .all(|c| c.is_ascii_alphanumeric() || c == b'-' || c == b'_')
    {
        return Err("desktop_account_credential_invalid".into());
    }
    Ok(token)
}

fn load_or_create(path: &Path) -> Result<String, String> {
    match fs::read(path) {
        Ok(bytes) => return decode(bytes),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
        Err(_) => return Err("desktop_account_credential_unavailable".into()),
    }
    let parent = path
        .parent()
        .ok_or("desktop_account_credential_unavailable")?;
    fs::create_dir_all(parent).map_err(|_| "desktop_account_credential_unavailable")?;
    let mut random = [0u8; 32];
    getrandom::fill(&mut random).map_err(|_| "desktop_account_credential_unavailable")?;
    let token = base64::engine::general_purpose::URL_SAFE_NO_PAD.encode(random);
    #[cfg(windows)]
    let bytes = [b"OAKDPAPI1\0".to_vec(), protect(token.as_bytes(), true)?].concat();
    #[cfg(not(windows))]
    let bytes = token.as_bytes().to_vec();
    let mut nonce = [0u8; 16];
    getrandom::fill(&mut nonce).map_err(|_| "desktop_account_credential_unavailable")?;
    let temporary = parent.join(format!(
        ".desktop-account-{}.tmp",
        base64::engine::general_purpose::URL_SAFE_NO_PAD.encode(nonce)
    ));
    let mut options = fs::OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let result = (|| {
        let mut file = options
            .open(&temporary)
            .map_err(|_| "desktop_account_credential_unavailable")?;
        file.write_all(&bytes)
            .and_then(|_| file.sync_all())
            .map_err(|_| "desktop_account_credential_unavailable")?;
        drop(file);
        // Publish a complete file without replacing a concurrent creator's key.
        match fs::hard_link(&temporary, path) {
            Ok(()) => Ok(token),
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {
                decode(fs::read(path).map_err(|_| "desktop_account_credential_unavailable")?)
            }
            Err(_) => Err("desktop_account_credential_unavailable".into()),
        }
    })();
    let _ = fs::remove_file(temporary);
    result
}

#[tauri::command]
pub(crate) fn openkitsune_account_session_token() -> Result<String, String> {
    let home = dirs_next::home_dir().ok_or("desktop_account_credential_unavailable")?;
    load_or_create(&home.join(".openkitsune").join(".desktop-account-token"))
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn persistent_native_token_survives_restart_and_concurrent_initialization() {
        let directory = std::env::temp_dir().join(format!(
            "openkitsune-account-native-test-{}",
            std::process::id()
        ));
        fs::create_dir_all(&directory).unwrap();
        let path = directory.join("token");
        let threads: Vec<_> = (0..6)
            .map(|_| {
                let path = path.clone();
                std::thread::spawn(move || load_or_create(&path).unwrap())
            })
            .collect();
        let values: Vec<_> = threads.into_iter().map(|t| t.join().unwrap()).collect();
        assert!(values.iter().all(|token| token == &values[0]));
        assert_eq!(load_or_create(&path).unwrap(), values[0]);
        #[cfg(windows)]
        assert!(!fs::read(&path)
            .unwrap()
            .windows(43)
            .any(|slice| slice == values[0].as_bytes()));
        fs::write(&path, b"invalid credential").unwrap();
        assert!(load_or_create(&path).is_err());
        fs::remove_dir_all(directory).unwrap();
    }
}
