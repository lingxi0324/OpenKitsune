#[cfg(any(target_os = "linux", test))]
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum LinuxGraphicsProfile {
    Default,
    FriendlyElecVendorMaliArm64,
}

#[cfg(any(target_os = "linux", test))]
const DEFAULT_LINUX_WEBKIT_ENV: &[(&str, &str)] = &[("WEBKIT_DISABLE_DMABUF_RENDERER", "1")];

#[cfg(any(target_os = "linux", test))]
const FRIENDLYELEC_VENDOR_MALI_ARM64_WEBKIT_ENV: &[(&str, &str)] = &[
    ("GDK_GL", "gles"),
    ("WEBKIT_DISABLE_DMABUF_RENDERER", "0"),
    ("WEBKIT_SKIA_ENABLE_CPU_RENDERING", "1"),
];

#[cfg(any(target_os = "linux", test))]
fn select_linux_graphics_profile(
    is_arm64: bool,
    is_friendlyelec_image: bool,
    has_vendor_mali_device: bool,
) -> LinuxGraphicsProfile {
    if is_arm64 && is_friendlyelec_image && has_vendor_mali_device {
        LinuxGraphicsProfile::FriendlyElecVendorMaliArm64
    } else {
        LinuxGraphicsProfile::Default
    }
}

#[cfg(any(target_os = "linux", test))]
fn defaults_for_profile(profile: LinuxGraphicsProfile) -> &'static [(&'static str, &'static str)] {
    match profile {
        LinuxGraphicsProfile::Default => DEFAULT_LINUX_WEBKIT_ENV,
        LinuxGraphicsProfile::FriendlyElecVendorMaliArm64 => {
            FRIENDLYELEC_VENDOR_MALI_ARM64_WEBKIT_ENV
        }
    }
}

#[cfg(any(target_os = "linux", test))]
fn apply_missing_defaults(
    defaults: &[(&'static str, &'static str)],
    mut is_set: impl FnMut(&str) -> bool,
    mut set: impl FnMut(&'static str, &'static str),
) -> Vec<&'static str> {
    let mut applied = Vec::new();
    for &(key, value) in defaults {
        if !is_set(key) {
            set(key, value);
            applied.push(key);
        }
    }
    applied
}

pub(crate) fn configure_webview_environment() {
    #[cfg(target_os = "linux")]
    {
        // FriendlyElec's proprietary Mali stack exposes /dev/mali0 and needs CPU Skia
        // rasterization to avoid stale WebKitGTK layers while retaining GPU compositing.
        let profile = select_linux_graphics_profile(
            cfg!(target_arch = "aarch64"),
            std::path::Path::new("/etc/friendlyelec-release").is_file(),
            std::path::Path::new("/dev/mali0").exists(),
        );
        let applied = apply_missing_defaults(
            defaults_for_profile(profile),
            |key| std::env::var_os(key).is_some(),
            |key, value| std::env::set_var(key, value),
        );

        if profile == LinuxGraphicsProfile::FriendlyElecVendorMaliArm64 {
            eprintln!(
                "[graphics] detected FriendlyElec ARM64 vendor Mali; applied WebKitGTK defaults: {}",
                if applied.is_empty() {
                    "none (environment already configured)".to_string()
                } else {
                    applied.join(", ")
                }
            );
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashSet;

    #[test]
    fn selects_profile_only_for_friendlyelec_arm64_with_mali_device() {
        assert_eq!(
            select_linux_graphics_profile(true, true, true),
            LinuxGraphicsProfile::FriendlyElecVendorMaliArm64
        );
        assert_eq!(
            select_linux_graphics_profile(false, true, true),
            LinuxGraphicsProfile::Default
        );
        assert_eq!(
            select_linux_graphics_profile(true, false, true),
            LinuxGraphicsProfile::Default
        );
        assert_eq!(
            select_linux_graphics_profile(true, true, false),
            LinuxGraphicsProfile::Default
        );
    }

    #[test]
    fn vendor_mali_profile_uses_tested_hybrid_rendering_defaults() {
        assert_eq!(
            defaults_for_profile(LinuxGraphicsProfile::FriendlyElecVendorMaliArm64),
            [
                ("GDK_GL", "gles"),
                ("WEBKIT_DISABLE_DMABUF_RENDERER", "0"),
                ("WEBKIT_SKIA_ENABLE_CPU_RENDERING", "1"),
            ]
        );
    }

    #[test]
    fn default_profile_preserves_existing_linux_dmabuf_workaround() {
        assert_eq!(
            defaults_for_profile(LinuxGraphicsProfile::Default),
            [("WEBKIT_DISABLE_DMABUF_RENDERER", "1")]
        );
    }

    #[test]
    fn explicit_environment_values_take_precedence() {
        let existing = HashSet::from(["GDK_GL", "WEBKIT_SKIA_ENABLE_CPU_RENDERING"]);
        let mut writes = Vec::new();

        let applied = apply_missing_defaults(
            FRIENDLYELEC_VENDOR_MALI_ARM64_WEBKIT_ENV,
            |key| existing.contains(key),
            |key, value| writes.push((key, value)),
        );

        assert_eq!(applied, ["WEBKIT_DISABLE_DMABUF_RENDERER"]);
        assert_eq!(writes, [("WEBKIT_DISABLE_DMABUF_RENDERER", "0")]);
    }
}
