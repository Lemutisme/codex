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
    /// Apply an authenticated kernel command read as JSON from stdin; print the new contract state.
    Apply {
        #[arg(long)]
        store: PathBuf,
        /// Idempotency key: replaying the same command under the same key is a no-op.
        #[arg(long)]
        key: String,
    },
    /// Print a contract's current state as JSON (`null` when it does not exist).
    Contract {
        #[arg(long)]
        store: PathBuf,
        #[arg(long)]
        id: String,
    },
    /// Print the domain-separated digest of a JSON value read from stdin.
    Digest {
        #[arg(long)]
        domain: String,
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
        Command::Apply { store, key } => {
            let mut command = String::new();
            std::io::stdin().read_to_string(&mut command)?;
            let contract = cli::apply_command(&store, &key, &command).await?;
            println!("{}", serde_json::to_string(&contract)?);
        }
        Command::Contract { store, id } => {
            let contract = cli::contract_command(&store, &id).await?;
            println!("{}", serde_json::to_string(&contract)?);
        }
        Command::Digest { domain } => {
            let mut value = String::new();
            std::io::stdin().read_to_string(&mut value)?;
            println!("{}", cli::digest_command(&domain, &value)?);
        }
    }
    Ok(())
}
