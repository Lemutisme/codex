use std::io::Read;
use std::path::PathBuf;

use clap::Parser;
use clap::Subcommand;
use codex_pro_contract_store::cli;

#[derive(Parser)]
#[command(about = "Operator access to a ProContract store")]
struct Args {
    #[command(subcommand)]
    command: Command,
}

#[derive(Subcommand)]
enum Command {
    /// Capture a workspace and print its subject hash, manifest and capture policy as JSON.
    Capture {
        #[arg(long)]
        store: PathBuf,
        #[arg(long)]
        root: PathBuf,
        #[arg(long = "exclude")]
        exclude: Vec<String>,
    },
    /// Write a captured subject into a directory.
    Materialize {
        #[arg(long)]
        store: PathBuf,
        #[arg(long)]
        subject: String,
        #[arg(long)]
        dest: PathBuf,
    },
    /// Append an experiment event read as JSON from stdin.
    Append {
        #[arg(long)]
        store: PathBuf,
    },
    /// Print all experiment events as a JSON array.
    Events {
        #[arg(long)]
        store: PathBuf,
    },
    /// Exit zero when the experiment chain verifies.
    Verify {
        #[arg(long)]
        store: PathBuf,
    },
}

#[tokio::main(flavor = "current_thread")]
async fn main() -> cli::CliResult<()> {
    match Args::parse().command {
        Command::Capture {
            store,
            root,
            exclude,
        } => {
            let captured = cli::capture_command(&store, &root, &exclude).await?;
            println!("{}", serde_json::to_string(&captured)?);
        }
        Command::Materialize {
            store,
            subject,
            dest,
        } => {
            cli::materialize_command(&store, &subject, &dest).await?;
        }
        Command::Append { store } => {
            let mut event = String::new();
            std::io::stdin().read_to_string(&mut event)?;
            let appended = cli::append_command(&store, &event).await?;
            println!("{}", serde_json::to_string(&appended)?);
        }
        Command::Events { store } => {
            let events = cli::events_command(&store).await?;
            println!("{}", serde_json::to_string(&events)?);
        }
        Command::Verify { store } => cli::verify_command(&store).await?,
    }
    Ok(())
}
