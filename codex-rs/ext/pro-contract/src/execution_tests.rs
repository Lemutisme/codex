use super::*;

#[tokio::test]
async fn timeout_retains_facts_without_claiming_the_action_completed() {
    let root = tempfile::tempdir().unwrap();
    let journal = root.path().join("action");
    let mut command = Command::new("sh");
    command.args(["-c", "printf 'first completed observation\\n'; sleep 30"]);
    let output = run(
        command,
        &journal,
        Digest::of(b"original grant"),
        Duration::from_millis(150),
        None,
    )
    .await
    .unwrap();
    assert_eq!(output.receipt.state, ExecutionState::TimedOut);
    assert!(output.receipt.shutdown_confirmed);
    assert_eq!(output.stdout, "first completed observation\n");
    assert!(!output.receipt.completed());
    let saved: ExecutionReceipt =
        serde_json::from_slice(&std::fs::read(journal.join("execution.json")).unwrap()).unwrap();
    assert_eq!(saved, output.receipt);
    assert_eq!(
        std::fs::read(journal.join("stdout")).unwrap(),
        output.stdout.as_bytes()
    );
    let mut repeated = Command::new("sh");
    repeated.args(["-c", "echo must-not-reexecute"]);
    assert!(
        run(
            repeated,
            &journal,
            saved.binding,
            Duration::from_secs(1),
            None
        )
        .await
        .is_err()
    );
    assert_eq!(
        std::fs::read(journal.join("stdout")).unwrap(),
        output.stdout.as_bytes()
    );
}

#[tokio::test]
async fn cancelled_action_finalizes_and_kills_its_process_group() {
    let root = tempfile::tempdir().unwrap();
    let journal = root.path().join("action");
    let target = journal.clone();
    let task = tokio::spawn(async move {
        let mut command = Command::new("sh");
        command.args(["-c", "sleep 30 & echo $!; wait"]);
        run(
            command,
            &target,
            Digest::of(b"grant"),
            Duration::from_secs(30),
            None,
        )
        .await
    });
    let until = tokio::time::Instant::now() + Duration::from_secs(3);
    let pid = loop {
        if let Ok(text) = std::fs::read_to_string(journal.join("stdout"))
            && let Ok(pid) = text.trim().parse::<u32>()
        {
            break pid;
        }
        assert!(tokio::time::Instant::now() < until);
        tokio::time::sleep(Duration::from_millis(10)).await;
    };
    task.abort();
    let _ = task.await;
    let until = tokio::time::Instant::now() + Duration::from_secs(15);
    let saved: ExecutionReceipt = loop {
        let receipt: ExecutionReceipt =
            serde_json::from_slice(&std::fs::read(journal.join("execution.json")).unwrap())
                .unwrap();
        if receipt.finished_ms.is_some() {
            break receipt;
        }
        assert!(
            tokio::time::Instant::now() < until,
            "cancelled action was not finalized"
        );
        tokio::time::sleep(Duration::from_millis(10)).await;
    };
    assert_eq!(saved.state, ExecutionState::Cancelled);
    assert!(saved.shutdown_confirmed);
    assert!(!saved.completed());
    for _ in 0..100 {
        let stat = std::fs::read_to_string(format!("/proc/{pid}/stat"));
        if stat.is_err() || stat.unwrap().split(") ").nth(1).unwrap().starts_with('Z') {
            return;
        }
        tokio::time::sleep(Duration::from_millis(10)).await;
    }
    panic!("cancelled action left a live descendant");
}
