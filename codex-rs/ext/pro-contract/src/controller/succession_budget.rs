//! Durable, compare-and-swap admission for fresh executor sessions. Unknown launches stay spent.

use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_pro_contract::Digest;
use serde::Deserialize;
use serde::Serialize;

use crate::Ledger;
use crate::SuccessionSettings;

pub(super) const KIND: &str = "succession";

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub(super) struct Budget {
    pub grant: SuccessionSettings,
    pub started_ms: u64,
    pub deadline_ms: u64,
    pub launches: u32,
    pub pending: Option<String>,
    pub executors: Vec<String>,
    pub lessons: Vec<Lesson>,
    pub previous_executor_claim: String,
}

/// Host-observed failed artifact and bounded feedback; a hypothesis is not a verified lesson.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub(super) struct Lesson {
    pub subject: Digest,
    pub residual: String,
}

pub(super) fn now_ms() -> Result<u64, String> {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .ok()
        .and_then(|time| u64::try_from(time.as_millis()).ok())
        .ok_or_else(|| "invalid host clock".to_string())
}

impl Budget {
    pub(super) fn new(grant: SuccessionSettings, now: u64) -> Result<Self, String> {
        if grant.total_secs == 0 || grant.total_secs > u64::MAX / 1000 {
            return Err(
                "succession requires a positive representable original task lifetime".into(),
            );
        }
        Ok(Self {
            deadline_ms: now
                .checked_add(grant.total_secs * 1000)
                .ok_or("deadline overflow")?,
            grant,
            started_ms: now,
            launches: 0,
            pending: None,
            executors: Vec::new(),
            lessons: Vec::new(),
            previous_executor_claim: String::new(),
        })
    }

    pub(super) fn reserve(
        &self,
        session: String,
        lesson: Lesson,
        now: u64,
    ) -> Result<(Self, u64), String> {
        if self.pending.is_some() {
            return Err("previous executor lifetime is unresolved; no launch replayed".into());
        }
        if now < self.started_ms || now >= self.deadline_ms {
            return Err("original task deadline exhausted or clock moved backwards".into());
        }
        if self
            .grant
            .max_sessions
            .is_some_and(|limit| self.launches >= limit)
        {
            return Err("original successor allowance exhausted".into());
        }
        let mut next = self.clone();
        next.launches = next
            .launches
            .checked_add(1)
            .ok_or("session counter overflow")?;
        next.executors.push(session.clone());
        next.pending = Some(session);
        next.lessons.push(lesson);
        // Keep the latest three failures, not an ever-growing transcript.
        if next.lessons.len() > 3 {
            next.lessons.remove(/*index*/ 0);
        }
        // Allocation among execution and later assessment is a strategy choice. Admission
        // enforces the actual grant rather than subtracting guessed future work durations.
        Ok((next, self.deadline_ms))
    }

    pub(super) async fn replace(
        &self,
        ledger: &Ledger,
        key: &str,
        previous: Option<&Self>,
    ) -> Result<(), String> {
        match ledger
            .compare_exchange_record(KIND, key, previous, self)
            .await
        {
            Ok(true) => Ok(()),
            Ok(false) => Err("succession ownership changed; no duplicate executor started".into()),
            Err(error) => Err(error.to_string()),
        }
    }
}

#[cfg(test)]
#[path = "succession_budget_tests.rs"]
mod tests;
