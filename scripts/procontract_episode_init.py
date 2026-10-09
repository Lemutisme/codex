"""Derive future H terms from trusted source; never provision or authorize a run."""

import tomllib

import procontract_ph_protocol as protocol


def derive_h_terms(terms):
    plan = protocol.document(protocol.plan_path(terms))
    protocol.require(isinstance(plan, dict), "supervisor plan must be an object")
    if protocol.profile(plan.get("protocol")).protocol != protocol.H_PROTOCOL:
        return
    import procontract_benchmark_runner as runner
    import procontract_fixed_auditor_role as auditor_role
    import procontract_native_trace_binding as trace

    configuration = tomllib.loads(
        runner.config_toml(model=terms["model"], effort=terms["effort"])
    )
    provider = configuration["model_providers"][configuration["model_provider"]]
    derived = {
        "fixed_auditor": auditor_role.descriptor(
            {key: provider[key] for key in ("base_url", "env_key")}
        ),
        "native_notice_trace": dict(trace.PROFILE),
    }
    protocol.require(
        all(key not in terms or terms[key] == value for key, value in derived.items()),
        "derived H runtime profile differs from existing terms",
    )
    terms.update(derived)
