mod api;
mod app;
mod apriltag;
mod bench;
mod calibration;
mod camera;
mod clock;
mod config;
mod corpus;
mod decode;
mod health;
mod network;
mod nt;
mod overrides;
mod pipeline;
mod pose;
mod processor;
mod recording;
mod structs;
mod system;

use std::net::SocketAddr;
use std::path::PathBuf;

use clap::{Parser, Subcommand};

#[derive(Parser)]
#[command(version, about = "Team 581's AprilTag vision service")]
struct Cli {
    #[command(subcommand)]
    command: Command,
}

#[derive(Subcommand)]
enum Command {
    /// Run the vision service.
    Run {
        /// Persistent state: cached robot inputs, overrides, and settings.
        #[arg(long, default_value = "/var/lib/spot-vision")]
        state_dir: PathBuf,
        /// Address to serve HTTP on; repeat to listen on several.
        #[arg(long, default_value = "0.0.0.0:5800")]
        listen: Vec<SocketAddr>,
        /// Built dashboard to serve at `/`.
        #[arg(long)]
        web_dir: Option<PathBuf>,
        /// Built documentation to serve at `/docs/`.
        #[arg(long)]
        docs_dir: Option<PathBuf>,
        /// Team number to use until one is set on the dashboard.
        #[arg(long)]
        team: Option<u16>,
        /// Short Git commit this build came from.
        #[arg(long)]
        revision: Option<String>,
        /// Unix time of that commit.
        #[arg(long)]
        commit_time: Option<i64>,
        /// Use each `*.jpg` in this folder as a camera instead of V4L2 devices.
        #[arg(long)]
        replay: Option<PathBuf>,
    },
    /// Print the HTTP API's OpenAPI document.
    Openapi,
    /// Print the robot config's JSON Schema.
    ConfigSchema,
    /// Time decoding, detection, and pose solving on JPEG files.
    Bench(bench::Bench),
    /// Score detection accuracy and speed on labelled grayscale frames.
    Corpus(corpus::Corpus),
}

fn filter() -> tracing_subscriber::EnvFilter {
    tracing_subscriber::EnvFilter::try_from_default_env().unwrap_or_else(|_| "info".into())
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let cli = Cli::parse();
    if !matches!(cli.command, Command::Run { .. }) {
        tracing_subscriber::fmt().with_env_filter(filter()).init();
    }
    match cli.command {
        Command::Openapi => println!("{}", api::openapi().to_pretty_json()?),
        Command::Bench(bench) => bench.run()?,
        Command::Corpus(corpus) => corpus.run()?,
        Command::ConfigSchema => {
            let schema = schemars::schema_for!(config::RobotConfig);
            println!("{}", serde_json::to_string_pretty(&schema)?);
        }
        Command::Run {
            state_dir,
            listen,
            web_dir,
            docs_dir,
            team,
            revision,
            commit_time,
            replay,
        } => {
            use tracing_subscriber::prelude::*;
            std::fs::create_dir_all(&state_dir)?;
            let recorder = recording::Recorder::new(&state_dir);
            tracing_subscriber::registry()
                .with(tracing_subscriber::fmt::layer().with_filter(filter()))
                .with(recording::LogLayer(recorder.clone()).with_filter(filter()))
                .init();
            let build = app::Build { revision, commit_time };
            let app = app::App::new(&state_dir, replay.as_deref(), team, build, recorder);
            app.start();
            let router = api::app(app, web_dir.as_deref(), docs_dir.as_deref());
            let mut servers = tokio::task::JoinSet::new();
            for address in listen {
                let listener = tokio::net::TcpListener::bind(address).await?;
                tracing::info!(%address, "serving");
                servers.spawn(axum::serve(listener, router.clone()).into_future());
            }
            let _ = sd_notify::notify(&[sd_notify::NotifyState::Ready]);
            tokio::select! {
                Some(result) = servers.join_next() => result??,
                _ = tokio::signal::ctrl_c() => {}
            }
        }
    }
    Ok(())
}
