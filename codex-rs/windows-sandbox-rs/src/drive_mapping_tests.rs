use super::DriveMappingResolver;
use super::ElevatedSandboxPathRequest;
use super::ElevatedSandboxPaths;
use super::resolve_elevated_sandbox_paths;
use super::resolve_path_for_elevated_sandbox;
use crate::winutil::to_wide;
use codex_protocol::models::ManagedFileSystemPermissions;
use codex_protocol::models::PermissionProfile;
use codex_protocol::permissions::FileSystemAccessMode;
use codex_protocol::permissions::FileSystemPath;
use codex_protocol::permissions::FileSystemSandboxEntry;
use codex_protocol::permissions::NetworkSandboxPolicy;
use codex_utils_absolute_path::AbsolutePathBuf;
use pretty_assertions::assert_eq;
use std::collections::HashMap;
use std::path::Path;
use std::path::PathBuf;
use tempfile::TempDir;
use windows_sys::Win32::Storage::FileSystem::DDD_EXACT_MATCH_ON_REMOVE;
use windows_sys::Win32::Storage::FileSystem::DDD_RAW_TARGET_PATH;
use windows_sys::Win32::Storage::FileSystem::DDD_REMOVE_DEFINITION;
use windows_sys::Win32::Storage::FileSystem::DefineDosDeviceW;

struct TemporaryDosDevice {
    name: String,
    target: String,
}

impl TemporaryDosDevice {
    fn create(target: &Path) -> Self {
        Self::create_raw(&format!(r"\??\{}", target.display()))
    }

    fn create_raw(target: &str) -> Self {
        let name = (b'D'..=b'Z')
            .rev()
            .find(|letter| super::query_dos_device_target(*letter).is_err())
            .map(|letter| format!("{}:", char::from(letter)))
            .expect("unused drive letter");
        let target = target.to_string();
        let name_wide = to_wide(&name);
        let target_wide = to_wide(&target);
        let created = unsafe {
            DefineDosDeviceW(
                DDD_RAW_TARGET_PATH,
                name_wide.as_ptr(),
                target_wide.as_ptr(),
            )
        };
        assert_ne!(created, 0, "DefineDosDeviceW failed: {}", unsafe {
            windows_sys::Win32::Foundation::GetLastError()
        });
        Self { name, target }
    }

    fn path(&self, relative: &str) -> PathBuf {
        PathBuf::from(format!(r"{}\{relative}", self.name))
    }
}

impl Drop for TemporaryDosDevice {
    fn drop(&mut self) {
        let name_wide = to_wide(&self.name);
        let target_wide = to_wide(&self.target);
        let removed = unsafe {
            DefineDosDeviceW(
                DDD_REMOVE_DEFINITION | DDD_EXACT_MATCH_ON_REMOVE | DDD_RAW_TARGET_PATH,
                name_wide.as_ptr(),
                target_wide.as_ptr(),
            )
        };
        if removed == 0 {
            let error = unsafe { windows_sys::Win32::Foundation::GetLastError() };
            if std::thread::panicking() {
                eprintln!("DefineDosDeviceW cleanup failed during unwind: {error}");
            } else {
                panic!("DefineDosDeviceW cleanup failed: {error}");
            }
        }
    }
}

#[test]
fn rejects_unverified_virtual_drive_device() {
    let err = super::resolve_dos_device_target(
        Path::new(r"J:\workspace"),
        r"\Device\Volume{f5ae2bcb-da01-3bf2-8935-408102040811}",
    )
    .expect_err("virtual device target must fail closed");

    assert_eq!(
        err.to_string(),
        "Windows elevated sandbox cannot use J:\\workspace because drive J: uses a device target whose session-independent filesystem backing could not be verified (\\Device\\Volume{f5ae2bcb-da01-3bf2-8935-408102040811}); move the workspace to a local drive or use a path with a verified session-independent backing"
    );
}

#[test]
fn translates_elevated_request_paths_before_permission_materialization() {
    let backing = TempDir::new().expect("tempdir");
    let mapping = TemporaryDosDevice::create(backing.path());
    let virtual_mapping = TemporaryDosDevice::create_raw(r"\Device\Volume{unverified}");
    let mapped_workspace = mapping.path("workspace");
    std::fs::create_dir_all(&mapped_workspace).expect("create mapped workspace");
    assert!(
        mapped_workspace.exists(),
        "parent must resolve temporary mapping"
    );
    assert_eq!(
        resolve_path_for_elevated_sandbox(&mapped_workspace).expect("resolve mapped path"),
        backing.path().join("workspace")
    );
    let mapped_codex_home = mapping.path("codex-home");
    let mapped_program = mapping.path(r"tools\tool.exe");
    let mapped_temp = mapping.path("temp");
    let mapped_read = mapping.path("read");
    let mapped_write = mapping.path("write");
    let mapped_deny_read = mapping.path("deny-read");
    let mapped_deny_write = mapping.path("deny-write");
    let workspace_root =
        AbsolutePathBuf::from_absolute_path(&mapped_workspace).expect("absolute mapped workspace");
    let permission_profile = permission_profile_with_path(&mapped_write);
    let read_roots_override = vec![mapped_read];
    let write_roots_override = vec![mapped_write];
    let deny_read_paths_override = vec![mapped_deny_read];
    let deny_write_paths_override = vec![mapped_deny_write];

    let paths = resolve_elevated_sandbox_paths(ElevatedSandboxPathRequest {
        permission_profile: &permission_profile,
        workspace_roots: std::slice::from_ref(&workspace_root),
        codex_home: &mapped_codex_home,
        command: vec![mapped_program.display().to_string(), "--flag".to_string()],
        cwd: &mapped_workspace,
        env_map: HashMap::from([
            ("Temp".to_string(), mapped_temp.display().to_string()),
            (
                "HOME".to_string(),
                virtual_mapping.path("home").display().to_string(),
            ),
            ("NOT_A_PATH".to_string(), r"Z:\leave-as-data".to_string()),
        ]),
        read_roots_override: Some(&read_roots_override),
        write_roots_override: Some(&write_roots_override),
        deny_read_paths_override: &deny_read_paths_override,
        deny_write_paths_override: &deny_write_paths_override,
    })
    .expect("resolve elevated request paths");

    assert_eq!(
        paths,
        ElevatedSandboxPaths {
            permission_profile: permission_profile_with_path(&backing.path().join("write")),
            workspace_roots: vec![
                AbsolutePathBuf::from_absolute_path(backing.path().join("workspace"))
                    .expect("absolute backing workspace")
            ],
            codex_home: backing.path().join("codex-home"),
            command: vec![
                backing.path().join(r"tools\tool.exe").display().to_string(),
                "--flag".to_string(),
            ],
            cwd: backing.path().join("workspace"),
            env_map: HashMap::from([
                (
                    "Temp".to_string(),
                    backing.path().join("temp").display().to_string(),
                ),
                (
                    "HOME".to_string(),
                    virtual_mapping.path("home").display().to_string(),
                ),
                ("NOT_A_PATH".to_string(), r"Z:\leave-as-data".to_string()),
            ]),
            read_roots_override: Some(vec![backing.path().join("read")]),
            write_roots_override: Some(vec![backing.path().join("write")]),
            deny_read_paths_override: vec![backing.path().join("deny-read")],
            deny_write_paths_override: vec![backing.path().join("deny-write")],
        }
    );
}

#[test]
fn handles_verbatim_and_rejects_drive_relative_and_self_referential_paths() {
    assert_eq!(
        super::resolve_dos_device_target(Path::new(r"\\?\J:\nested\file.txt"), r"\??\C:\backing",)
            .expect("translate verbatim drive path"),
        super::DriveTargetResolution::Translated(PathBuf::from(r"C:\backing\nested\file.txt"))
    );

    let mut drive_relative = DriveMappingResolver::default();
    drive_relative
        .targets
        .insert(b'J', r"\??\C:\backing".to_string());
    assert_eq!(
        drive_relative
            .resolve(Path::new(r"J:relative"))
            .expect_err("drive-relative path must fail")
            .to_string(),
        r"Windows elevated sandbox requires an absolute drive path, but received J:relative"
    );

    let mut self_referential = DriveMappingResolver::default();
    self_referential
        .targets
        .insert(b'X', r"\??\X:\".to_string());
    assert!(
        self_referential
            .resolve(Path::new(r"X:\workspace"))
            .expect_err("self-referential mapping must fail")
            .to_string()
            .contains("made no resolution progress")
    );
}

fn permission_profile_with_path(path: &Path) -> PermissionProfile {
    PermissionProfile::Managed {
        file_system: ManagedFileSystemPermissions::Restricted {
            entries: vec![FileSystemSandboxEntry::new(
                FileSystemPath::Path {
                    path: AbsolutePathBuf::from_absolute_path(path)
                        .expect("absolute permission path"),
                },
                FileSystemAccessMode::Write,
            )],
            glob_scan_max_depth: None,
        },
        network: NetworkSandboxPolicy::Restricted,
    }
}
