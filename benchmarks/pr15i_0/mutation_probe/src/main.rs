//! PR15I-0 benchmark-only mutation-state byte attribution probe (CLI).
//!
//! Fixed CLI — no other flags or modes are accepted:
//!
//! ```text
//! mutation-probe --index-root <absolute prepared index dir> \
//!                --max-bytes <1..=268435456> \
//!                --source-sha <40 lowercase hex> \
//!                --out <absolute path under an ignored target tree>
//! ```
//!
//! The authoritative sidecar is located through the public
//! `CURRENT -> Manifest -> MutationStateRef` chain, so no file under
//! `index/state/` is ever guessed. Exactly one canonical JSON object is written
//! to `--out`; diagnostics go to stderr only. A failure exits non-zero with a
//! classified `{"class": …}` record on stderr and **no** JSON output file.

use std::collections::BTreeMap;
use std::ffi::OsString;
use std::fs;
use std::path::{Path, PathBuf};

use serde_json::{Value, json};

use pr15i0_mutation_probe::{
    MAX_SIDECAR_BYTES, ProbeError, is_lower_hex_sha, probe_index_root, report_json,
};

const EXIT_FAILED: i32 = 3;
const EXIT_USAGE: i32 = 2;

struct Args {
    index_root: PathBuf,
    max_bytes: u64,
    source_sha: String,
    out: PathBuf,
}

fn parse_args() -> Result<Args, ProbeError> {
    let mut index_root: Option<String> = None;
    let mut max_bytes: Option<u64> = None;
    let mut source_sha: Option<String> = None;
    let mut out: Option<String> = None;

    let mut arguments = std::env::args_os().skip(1);
    while let Some(raw) = arguments.next() {
        let flag = raw
            .to_str()
            .ok_or_else(|| usage("arguments must be valid UTF-8"))?
            .to_owned();
        let mut value = || -> Result<String, ProbeError> {
            let next: OsString = arguments
                .next()
                .ok_or_else(|| usage(format!("{flag} requires a value")))?;
            next.into_string()
                .map_err(|_| usage(format!("{flag} value must be valid UTF-8")))
        };
        match flag.as_str() {
            "--index-root" => {
                let parsed = value()?;
                if index_root.replace(parsed).is_some() {
                    return Err(usage("--index-root was supplied more than once"));
                }
            }
            "--max-bytes" => {
                let parsed = value()?;
                let number = parsed.parse::<u64>().map_err(|_| {
                    usage(format!(
                        "--max-bytes is not a non-negative integer: {parsed}"
                    ))
                })?;
                if max_bytes.replace(number).is_some() {
                    return Err(usage("--max-bytes was supplied more than once"));
                }
            }
            "--source-sha" => {
                let parsed = value()?;
                if source_sha.replace(parsed).is_some() {
                    return Err(usage("--source-sha was supplied more than once"));
                }
            }
            "--out" => {
                let parsed = value()?;
                if out.replace(parsed).is_some() {
                    return Err(usage("--out was supplied more than once"));
                }
            }
            other => {
                return Err(usage(format!("unsupported argument: {other}")));
            }
        }
    }

    let index_root = PathBuf::from(index_root.ok_or_else(|| usage("--index-root is required"))?);
    let max_bytes = max_bytes.ok_or_else(|| usage("--max-bytes is required"))?;
    if max_bytes == 0 || max_bytes > MAX_SIDECAR_BYTES {
        return Err(usage(format!(
            "--max-bytes must be in 1..={MAX_SIDECAR_BYTES}, got {max_bytes}"
        )));
    }
    let source_sha = source_sha.ok_or_else(|| usage("--source-sha is required"))?;
    if !is_lower_hex_sha(&source_sha) {
        return Err(usage(
            "--source-sha must be 40 lowercase hexadecimal characters",
        ));
    }
    let out = out.ok_or_else(|| usage("--out is required"))?;
    let out = PathBuf::from(out);
    if !out.is_absolute() {
        return Err(usage("--out must be an absolute path"));
    }

    Ok(Args {
        index_root,
        max_bytes,
        source_sha,
        out,
    })
}

fn usage(message: impl Into<String>) -> ProbeError {
    ProbeError::classified("usage", message)
}

/// Serialize with sorted top-level keys and compact separators.
fn canonical_json(value: &Value) -> String {
    let Value::Object(map) = value else {
        return value.to_string();
    };
    let sorted: BTreeMap<&str, &Value> = map
        .iter()
        .map(|(key, child)| (key.as_str(), child))
        .collect();
    serde_json::to_string(&sorted).unwrap_or_else(|_| String::from("{}"))
}

fn write_output(path: &Path, payload: &str) -> Result<(), ProbeError> {
    if path.exists() {
        return Err(ProbeError::classified(
            "output_exists",
            format!("--out already exists: {}", path.display()),
        ));
    }
    let parent = path
        .parent()
        .ok_or_else(|| ProbeError::classified("invalid_path", "--out has no parent"))?;
    fs::create_dir_all(parent).map_err(|error| {
        ProbeError::classified("io", format!("cannot create output dir: {error}"))
    })?;
    let mut temporary = path.to_path_buf();
    temporary.set_extension("json.tmp");
    {
        use std::io::Write;
        let mut handle = fs::File::create(&temporary).map_err(|error| {
            ProbeError::classified(
                "io",
                format!("cannot create {}: {error}", temporary.display()),
            )
        })?;
        handle.write_all(payload.as_bytes()).map_err(|error| {
            ProbeError::classified(
                "io",
                format!("cannot write {}: {error}", temporary.display()),
            )
        })?;
        handle.write_all(b"\n").map_err(|error| {
            ProbeError::classified(
                "io",
                format!("cannot write {}: {error}", temporary.display()),
            )
        })?;
        handle.sync_all().map_err(|error| {
            ProbeError::classified(
                "io",
                format!("cannot sync {}: {error}", temporary.display()),
            )
        })?;
    }
    // `link` gives exclusive creation: an existing destination is never replaced.
    fs::hard_link(&temporary, path).map_err(|error| {
        ProbeError::classified(
            "output_exists",
            format!("cannot publish {}: {error}", path.display()),
        )
    })?;
    fs::remove_file(&temporary).map_err(|error| {
        ProbeError::classified("io", format!("cannot remove temporary output: {error}"))
    })?;
    Ok(())
}

fn main() {
    let code = match run() {
        Ok(()) => 0,
        Err(error) => {
            let record = json!({
                "schema": "pr15i-0-mutation-probe-error-v1",
                "status": "FAILED",
                "class": error.class(),
                "detail": error.detail(),
            });
            eprintln!("{}", canonical_json(&record));
            eprintln!("{error}");
            if error.class() == "usage" {
                EXIT_USAGE
            } else {
                EXIT_FAILED
            }
        }
    };
    std::process::exit(code);
}

fn run() -> Result<(), ProbeError> {
    let args = parse_args()?;
    let report = probe_index_root(&args.index_root, args.max_bytes, &args.source_sha)?;
    let payload = report_json(&report, &args.source_sha);
    write_output(&args.out, &canonical_json(&payload))?;
    let summary = json!({
        "schema": payload.get("schema").cloned().unwrap_or(Value::Null),
        "status": "CAPTURED",
        "payload_version": payload.get("payload_version").cloned().unwrap_or(Value::Null),
        "sidecar_file_bytes": payload.get("sidecar_file_bytes").cloned().unwrap_or(Value::Null),
        "payload_bytes": payload.get("payload_bytes").cloned().unwrap_or(Value::Null),
        "sidecar_sha256": payload.get("sidecar_sha256").cloned().unwrap_or(Value::Null),
        "out": args.out.display().to_string(),
    });
    println!("{}", canonical_json(&summary));
    Ok(())
}
