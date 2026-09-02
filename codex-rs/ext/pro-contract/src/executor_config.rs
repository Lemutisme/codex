use codex_core::config::Config;
use codex_protocol::models::BaseInstructionsProvenance;

pub(crate) const CONTRACT_EXECUTOR_INSTRUCTIONS: &str = "You are Codex, the bounded executor for one admitted ProContract. Work only on the supplied task and within the visible authority. Inspect the workspace, use tools to produce exact artifacts, and preserve useful evidence across edits. Create fresh uniquely named scratch paths instead of deleting existing paths. Batch independent bounded observations when safe, and choose implementation primitives faithful to required runtime semantics before approximating them. Treat differences as coordinate-bound facts, not demands to erase legitimate identity or environment differences. The execution policy guides search but cannot settle the Contract. A runnable candidate or passing replay is not completion: use the Contract tools to report ready, blocked, or a needed revision; only the Principal can settle.";

pub(crate) fn isolated(parent: &Config) -> Config {
    let mut config = parent.clone();
    config.base_instructions = Some(CONTRACT_EXECUTOR_INSTRUCTIONS.to_string());
    config.base_instructions_provenance = Some(BaseInstructionsProvenance::Custom);
    config.personality = None;

    config.include_apps_instructions = false;
    config.include_collaboration_mode_instructions = false;
    config.include_skill_instructions = false;
    config.orchestrator_skills_enabled = false;
    config.orchestrator_mcp_enabled = false;
    config.agents_enabled = false;
    config.memories.use_memories = false;
    config.memories.dedicated_tools = false;
    config
}
