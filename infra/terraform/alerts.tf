# Alerting on the daily run.
#
# Two policies, on two signals that do not say the same thing, and the whole point is that they stay
# apart: a failure means the run produced no digest, a truncation means a cap cut in and the digest
# exists but is incomplete. Merging them would make a daily truncation read as an outage, or the
# reverse — and truncation is expected on a heavy batch, so an alert that cried failure for it would
# be muted within the week and then miss the real outage.
#
# Log-match conditions rather than log-based metrics: the signal is the presence of a line, not a
# rate. A metric would need a threshold and a window, both of which would be invented — there is no
# measurement to set them from, and this file exists precisely to avoid arbitrary thresholds dressed
# up as configuration.
#
# These were written in the runbook (§9) on 2026-08-23 and stayed unarmed until 2026-09-06. That gap
# is the point of declaring them here: a query written in a document is a hypothesis, a resource in
# the state is a thing that exists.

variable "enable_alerts" {
  description = <<-EOT
    Creates the two alert policies on the daily run. True by default since 2026-09-06, when the
    scheduler was armed: an unattended run with no alert is the one configuration that must not
    persist.
  EOT
  type        = bool
  default     = true
}

variable "alert_email" {
  description = <<-EOT
    Address the alerts are delivered to. Empty by default, and deliberately without a value in the
    repository: an address committed here would be published with the code.

    Left empty, the policies are still created and still fire — they show in the Monitoring console
    and in the incident list — but notify nobody. Set it with
    `terraform apply -var="alert_email=..."`, or in a local tfvars file that is not committed.
  EOT
  type        = string
  default     = ""
}

locals {
  alert_channels = var.alert_email == "" ? [] : [google_monitoring_notification_channel.email[0].id]

  # Both policies are scoped to the Job by name, not to the whole project: the service serves the
  # digest and its errors are a different problem, on a different path, with a different urgency.
  job_filter = "resource.type=\"cloud_run_job\" resource.labels.job_name=\"${google_cloud_run_v2_job.daily.name}\""
}

resource "google_monitoring_notification_channel" "email" {
  count = var.enable_alerts && var.alert_email != "" ? 1 : 0

  project      = var.project_id
  display_name = "VIGIE-01 operator"
  type         = "email"

  labels = {
    email_address = var.alert_email
  }
}

resource "google_monitoring_alert_policy" "run_failed" {
  count = var.enable_alerts ? 1 : 0

  project      = var.project_id
  display_name = "VIGIE-01 — daily run failed"
  combiner     = "OR"

  conditions {
    display_name = "ERROR in the Cloud Run Job"

    condition_matched_log {
      # `severity>=ERROR` and not a message match: backend/logging_setup.py puts the severity in the
      # `severity` field, the only one Cloud Logging promotes, precisely so that this filter can be
      # written on a field rather than by grepping free text. An unreachable feed already logs at
      # ERROR (backend/agents/collector.py), so a collection hole reaches this policy too.
      filter = "${local.job_filter} severity>=ERROR"
    }
  }

  alert_strategy {
    # One notification an hour at most. A run that fails on import fails identically on every line it
    # then writes; the interesting event is the first one.
    notification_rate_limit {
      period = "3600s"
    }
  }

  notification_channels = local.alert_channels

  documentation {
    content   = <<-EOT
      The daily run logged an ERROR. Two families to tell apart before doing anything:

      - `unreachable sources` — one feed failed, the run continued with the others. The digest exists
        and is short by that source. Nothing to restart.
      - anything else — the run itself failed and produced no digest. `--max-retries 0` on the Job
        means it will not have retried on its own, deliberately: a blind retry spends tomorrow's
        budget on the same fault.

      The daily budget is a global counter: a failed run may still have spent most of it before
      failing. Check `llm_calls_by_node` on the last `run finished` line before relaunching anything.
    EOT
    mime_type = "text/markdown"
  }
}

resource "google_monitoring_alert_policy" "run_truncated" {
  count = var.enable_alerts ? 1 : 0

  project      = var.project_id
  display_name = "VIGIE-01 — daily run truncated by a cap"
  combiner     = "OR"

  conditions {
    display_name = "truncated=true in the Cloud Run Job"

    condition_matched_log {
      # A structured field, not a phrase in the message. That is the whole reason the measurements are
      # emitted as fields (backend/logging_setup.py): a truncation filters on
      # `jsonPayload.truncated=true` and survives any rewording of the log line.
      filter = "${local.job_filter} jsonPayload.truncated=true"
    }
  }

  alert_strategy {
    # A day at most. A truncation is a property of the run, not of the line: the three nodes each log
    # their own, and one notification for the day is the useful granularity.
    notification_rate_limit {
      period = "86400s"
    }
  }

  notification_channels = local.alert_channels

  documentation {
    content   = <<-EOT
      A cap stopped the run before the end of the batch. **This is a partial success, not a failure**:
      the items already analysed are recorded and served, and the Job exited 0 on purpose so that
      Cloud Run would not retry it.

      What to read, in this order, on the `run finished` line:

      - `llm_calls_by_node` — which node absorbed the shortfall. `thread` is last in the chain, so it
        is normally the one that pays.
      - `analyze_by_source` — how much of the budget went on items that were then discarded, and for
        what reason. Above roughly two thirds, the fix is at collection time, not in the caps.

      One truncation on a heavy batch is expected. Several days in a row means the caps and the batch
      size no longer match, which is an arbitration (docs/scoping.md §11), not an incident.
    EOT
    mime_type = "text/markdown"
  }
}
