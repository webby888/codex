use crate::logging::debug_log;
use crate::winutil::to_wide;
use anyhow::Context;
use anyhow::Result;
use codex_protocol::models::ManagedFileSystemPermissions;
use codex_protocol::models::PermissionProfile;
use codex_protocol::permissions::FileSystemPath;
use codex_protocol::permissions::FileSystemSandboxEntry;
use codex_utils_absolute_path::AbsolutePathBuf;
use std::collections::HashMap;
use std::path::Component;
use std::path::Path;
use std::path::PathBuf;
use std::path::Prefix;
use windows_sys::Win32::Foundation::GetLastError;
use windows_sys::Win32::Storage::FileSystem::QueryDosDeviceW;

const MAX_NESTED_DRIVE_MAPPINGS: usize = 8;
const PATH_ENV_KEYS: &[&str] = &[
    "HOME",
    "OLDPWD",
    "PWD",
    "TEMP",
    "TMP",
    "TMPDIR",
    "USERPROFILE",
];

pub(crate) struct ElevatedSandboxPathRequest<'a> {
    pub(crate) permission_profile: &'a PermissionProfile,
    pub(crate) workspace_roots: &'a [AbsolutePathBuf],
    pub(crate) codex_home: &'a Path,
    pub(crate) command: Vec<String>,
    pub(crate) cwd: &'a Path,
    pub(crate) env_map: HashMap<String, String>,
    pub(crate) read_roots_override: Option<&'a [PathBuf]>,
    pub(crate) write_roots_override: Option<&'a [PathBuf]>,
    pub(crate) deny_read_paths_override: &'a [PathBuf],
    pub(crate) deny_write_paths_override: &'a [PathBuf],
}

#[derive(Debug, PartialEq, Eq)]
pub(crate) struct ElevatedSandboxPaths {
    pub(crate) permission_profile: PermissionProfile,
    pub(crate) workspace_roots: Vec<AbsolutePathBuf>,
    pub(crate) codex_home: PathBuf,
    pub(crate) command: Vec<String>,
    pub(crate) cwd: PathBuf,
    pub(crate) env_map: HashMap<String, String>,
    pub(crate) read_roots_override: Option<Vec<PathBuf>>,
    pub(crate) write_roots_override: Option<Vec<PathBuf>>,
    pub(crate) deny_read_paths_override: Vec<PathBuf>,
    pub(crate) deny_write_paths_override: Vec<PathBuf>,
}

pub(crate) fn resolve_path_for_elevated_sandbox(path: &Path) -> Result<PathBuf> {
    DriveMappingResolver::default().resolve(path)
}

#[derive(Debug, Eq, PartialEq)]
enum DriveTargetResolution {
    Stable,
    Translated(PathBuf),
}

#[derive(Default)]
struct DriveMappingResolver {
    targets: HashMap<u8, String>,
}

impl DriveMappingResolver {
    fn resolve(&mut self, path: &Path) -> Result<PathBuf> {
        let mut resolved = path.to_path_buf();
        for _ in 0..MAX_NESTED_DRIVE_MAPPINGS {
            let Some(drive_letter) = drive_letter(&resolved) else {
                return Ok(resolved);
            };
            if !resolved.is_absolute() {
                anyhow::bail!(
                    "Windows elevated sandbox requires an absolute drive path, but received {}",
                    resolved.display()
                );
            }
            let target = self.target(drive_letter)?.to_string();
            match resolve_dos_device_target(&resolved, &target)? {
                DriveTargetResolution::Stable => return Ok(resolved),
                DriveTargetResolution::Translated(next) => {
                    if next == resolved {
                        anyhow::bail!(
                            "Windows elevated sandbox drive mapping for {} made no resolution progress ({target})",
                            resolved.display()
                        );
                    }
                    resolved = next;
                }
            }
        }
        anyhow::bail!(
            "Windows elevated sandbox path resolution exceeded {MAX_NESTED_DRIVE_MAPPINGS} nested drive mappings for {}",
            path.display()
        )
    }

    fn target(&mut self, drive_letter: u8) -> Result<&str> {
        if let std::collections::hash_map::Entry::Vacant(e) = self.targets.entry(drive_letter) {
            let target = query_dos_device_target(drive_letter)?;
            e.insert(target);
        }
        self.targets
            .get(&drive_letter)
            .map(String::as_str)
            .context("cached DOS device target disappeared")
    }
}

fn query_dos_device_target(drive_letter: u8) -> Result<String> {
    let device_name = format!("{}:", char::from(drive_letter));
    let device_name_wide = to_wide(&device_name);
    let mut target = vec![0u16; 32_768];
    let target_len = unsafe {
        QueryDosDeviceW(
            device_name_wide.as_ptr(),
            target.as_mut_ptr(),
            target.len() as u32,
        )
    };
    if target_len == 0 {
        let error = unsafe { GetLastError() };
        anyhow::bail!(
            "failed to inspect drive {device_name} before Windows elevated sandbox launch: Windows error {error}"
        );
    }
    let target_end = target
        .iter()
        .position(|value| *value == 0)
        .unwrap_or(target_len as usize);
    let target = String::from_utf16(&target[..target_end])
        .context("decode QueryDosDeviceW target as UTF-16")?;
    Ok(target)
}

fn drive_letter(path: &Path) -> Option<u8> {
    match path.components().next()? {
        Component::Prefix(prefix) => match prefix.kind() {
            Prefix::Disk(letter) | Prefix::VerbatimDisk(letter) => {
                Some(letter.to_ascii_uppercase())
            }
            Prefix::Verbatim(_)
            | Prefix::VerbatimUNC(_, _)
            | Prefix::DeviceNS(_)
            | Prefix::UNC(_, _) => None,
        },
        Component::RootDir | Component::CurDir | Component::ParentDir | Component::Normal(_) => {
            None
        }
    }
}

fn resolve_dos_device_target(path: &Path, target: &str) -> Result<DriveTargetResolution> {
    let Some(drive_letter) = drive_letter(path) else {
        anyhow::bail!(
            "cannot resolve DOS device target {target} for non-drive path {}",
            path.display()
        );
    };
    if target.starts_with(r"\Device\HarddiskVolume") {
        return Ok(DriveTargetResolution::Stable);
    }

    if let Some(backing) = target.strip_prefix(r"\??\") {
        let backing = if let Some(unc) = backing.strip_prefix(r"UNC\") {
            PathBuf::from(format!(r"\\{unc}"))
        } else {
            PathBuf::from(backing)
        };
        if backing.is_absolute() {
            let relative = path_after_drive_root(path)?;
            return Ok(DriveTargetResolution::Translated(backing.join(relative)));
        }
    }

    let device_name = format!("{}:", char::from(drive_letter));
    anyhow::bail!(
        "Windows elevated sandbox cannot use {} because drive {device_name} uses a device target whose session-independent filesystem backing could not be verified ({target}); move the workspace to a local drive or use a path with a verified session-independent backing",
        path.display()
    )
}

fn path_after_drive_root(path: &Path) -> Result<PathBuf> {
    let mut components = path.components();
    let prefix = components.next();
    let root = components.next();
    if !matches!(prefix, Some(Component::Prefix(_))) || !matches!(root, Some(Component::RootDir)) {
        anyhow::bail!(
            "Windows elevated sandbox requires an absolute drive path, but received {}",
            path.display()
        );
    }
    Ok(components.collect())
}

pub(crate) fn resolve_elevated_sandbox_paths(
    request: ElevatedSandboxPathRequest<'_>,
) -> Result<ElevatedSandboxPaths> {
    let mut resolver = DriveMappingResolver::default();
    let permission_profile = resolve_permission_profile(&mut resolver, request.permission_profile)?;
    let workspace_roots = request
        .workspace_roots
        .iter()
        .map(|path| resolve_absolute_path(&mut resolver, path))
        .collect::<Result<Vec<_>>>()?;
    let codex_home = resolver.resolve(request.codex_home)?;
    let cwd = resolver.resolve(request.cwd)?;
    let mut command = request.command;
    if let Some(program) = command.first_mut() {
        let program_path = Path::new(program);
        if program_path.is_absolute() {
            *program = resolver
                .resolve(program_path)?
                .to_string_lossy()
                .into_owned();
        }
    }
    let mut env_map = request.env_map;
    for (key, value) in &mut env_map {
        if !PATH_ENV_KEYS
            .iter()
            .any(|path_key| key.eq_ignore_ascii_case(path_key))
        {
            continue;
        }
        let path = Path::new(value);
        if path.is_absolute() {
            match resolver.resolve(path) {
                Ok(path) => *value = path.to_string_lossy().into_owned(),
                Err(err) => debug_log(
                    &format!(
                        "leaving elevated sandbox environment variable {key} unchanged because its drive mapping could not be resolved: {err:#}"
                    ),
                    None,
                ),
            }
        }
    }

    Ok(ElevatedSandboxPaths {
        permission_profile,
        workspace_roots,
        codex_home,
        command,
        cwd,
        env_map,
        read_roots_override: resolve_optional_paths(&mut resolver, request.read_roots_override)?,
        write_roots_override: resolve_optional_paths(&mut resolver, request.write_roots_override)?,
        deny_read_paths_override: resolve_paths(&mut resolver, request.deny_read_paths_override)?,
        deny_write_paths_override: resolve_paths(&mut resolver, request.deny_write_paths_override)?,
    })
}

fn resolve_permission_profile(
    resolver: &mut DriveMappingResolver,
    permission_profile: &PermissionProfile,
) -> Result<PermissionProfile> {
    match permission_profile {
        PermissionProfile::Managed {
            file_system:
                ManagedFileSystemPermissions::Restricted {
                    entries,
                    glob_scan_max_depth,
                },
            network,
        } => Ok(PermissionProfile::Managed {
            file_system: ManagedFileSystemPermissions::Restricted {
                entries: entries
                    .iter()
                    .map(|entry| resolve_file_system_entry(resolver, entry))
                    .collect::<Result<Vec<_>>>()?,
                glob_scan_max_depth: *glob_scan_max_depth,
            },
            network: *network,
        }),
        PermissionProfile::Managed {
            file_system: ManagedFileSystemPermissions::Unrestricted,
            network,
        } => Ok(PermissionProfile::Managed {
            file_system: ManagedFileSystemPermissions::Unrestricted,
            network: *network,
        }),
        PermissionProfile::Disabled => Ok(PermissionProfile::Disabled),
        PermissionProfile::External { network } => {
            Ok(PermissionProfile::External { network: *network })
        }
    }
}

fn resolve_file_system_entry(
    resolver: &mut DriveMappingResolver,
    entry: &FileSystemSandboxEntry,
) -> Result<FileSystemSandboxEntry> {
    let mut entry = entry.clone();
    entry.path = match &entry.path {
        FileSystemPath::Path { path } => FileSystemPath::Path {
            path: resolve_absolute_path(resolver, path)?,
        },
        FileSystemPath::GlobPattern { pattern } => {
            let pattern_path = Path::new(pattern);
            if drive_letter(pattern_path).is_some() {
                FileSystemPath::GlobPattern {
                    pattern: resolver
                        .resolve(pattern_path)?
                        .to_string_lossy()
                        .into_owned(),
                }
            } else {
                entry.path.clone()
            }
        }
        FileSystemPath::Special { .. } => entry.path.clone(),
    };
    Ok(entry)
}

fn resolve_absolute_path(
    resolver: &mut DriveMappingResolver,
    path: &AbsolutePathBuf,
) -> Result<AbsolutePathBuf> {
    let path = resolver.resolve(path.as_path())?;
    AbsolutePathBuf::from_absolute_path(path)
        .map_err(|err| anyhow::anyhow!("resolved elevated sandbox path is not absolute: {err}"))
}

fn resolve_paths(resolver: &mut DriveMappingResolver, paths: &[PathBuf]) -> Result<Vec<PathBuf>> {
    paths.iter().map(|path| resolver.resolve(path)).collect()
}

fn resolve_optional_paths(
    resolver: &mut DriveMappingResolver,
    paths: Option<&[PathBuf]>,
) -> Result<Option<Vec<PathBuf>>> {
    paths
        .map(|paths| resolve_paths(resolver, paths))
        .transpose()
}

#[cfg(test)]
#[path = "drive_mapping_tests.rs"]
mod tests;
