mod app;
mod account_native;
pub(crate) mod backend;
pub(crate) mod commands;
mod config;
pub(crate) mod crash_handler;
mod environment;
mod feedback;
pub(crate) mod finance;
mod graphics;
mod lifecycle;
pub(crate) mod migrations;
mod network;
mod python;
mod runtime;
mod workspace;

pub(crate) mod prelude {
    pub(crate) use crate::account_native::*;
    pub(crate) use crate::backend::*;
    pub(crate) use crate::config::*;
    pub(crate) use crate::environment::*;
    pub(crate) use crate::feedback::*;
    pub(crate) use crate::lifecycle::*;
    pub(crate) use crate::network::*;
    pub(crate) use crate::python::*;
    pub(crate) use crate::runtime::*;
    pub(crate) use crate::workspace::*;
    pub(crate) use crate::{commands, crash_handler, finance, migrations};

    pub(crate) use base64::Engine as _;
    pub(crate) use dirs_next::home_dir;
    pub(crate) use once_cell::sync::Lazy;
    pub(crate) use serde::{Deserialize, Serialize};
    pub(crate) use std::collections::{HashMap, HashSet, VecDeque};
    pub(crate) use std::fs;
    pub(crate) use std::fs::OpenOptions;
    pub(crate) use std::io::{Read, Seek, SeekFrom, Write};
    pub(crate) use std::net::{TcpStream, ToSocketAddrs};
    pub(crate) use std::path::{Path, PathBuf};
    pub(crate) use std::process::{Command, Stdio};
    pub(crate) use std::sync::atomic::{AtomicBool, AtomicU64, AtomicU8, Ordering};
    pub(crate) use std::sync::Mutex;
    pub(crate) use std::thread;
    pub(crate) use std::time::{Duration, Instant};
    pub(crate) use tauri::Manager;
    #[cfg(desktop)]
    pub(crate) use tauri_plugin_autostart::MacosLauncher;
    #[cfg(desktop)]
    pub(crate) use tauri_plugin_autostart::ManagerExt as AutostartManagerExt;
}

pub fn run() {
    app::run();
}
