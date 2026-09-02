"use client";

import type { PipelineEvent } from "@/lib/types";

const reviewSteps = [
  {
    label: "Understand",
    nodes: ["Load Conversation History", "Cross Reference Evaluator", "Query Rewriter", "Orchestrator"],
  },
  {
    label: "Find evidence",
    nodes: ["Retrieve Documents", "Re-rank Documents"],
  },
  {
    label: "Check sources",
    nodes: ["Document Relevance Evaluator", "Increment Retry Count", "Web Search Fallback"],
  },
  {
    label: "Prepare answer",
    nodes: ["Main LLM Call", "Safe Response", "Save Query and Response to Conversation Memory"],
  },
];

export function PipelineStepper({ events, complete = false }: { events: PipelineEvent[]; complete?: boolean }) {
  const latestByNode = new Map<string, PipelineEvent>();
  for (const event of events) {
    if (event.type === "stage" && event.node_name) {
      latestByNode.set(event.node_name, event);
    }
  }

  return (
    <div className="pipeline-shell">
      <div className="pipeline-progress-head">
        <div>
          <p className="eyebrow">Answer progress</p>
          <h3>{complete ? "Review complete" : "AuditReady is working"}</h3>
        </div>
        <span className={`trace-badge ${complete ? "complete" : ""}`}>{complete ? "Ready" : "Live"}</span>
      </div>
      <div className="pipeline-stepper">
        {reviewSteps.map((step, stepIndex) => {
          const matchingEvents = step.nodes.map((node) => latestByNode.get(node)).filter(Boolean) as PipelineEvent[];
          const activeEvent = [...matchingEvents].reverse().find((event) => event.status !== "completed");
          const lastEvent = matchingEvents.at(-1);
          const laterStepStarted = reviewSteps.slice(stepIndex + 1).some((laterStep) => laterStep.nodes.some((node) => latestByNode.has(node)));
          const status = complete
            ? "done"
            : activeEvent
              ? "active"
              : matchingEvents.length > 0 && (laterStepStarted || matchingEvents.every((event) => event.status === "completed"))
                ? "done"
                : "idle";
          return (
            <div key={step.label} className={`pipeline-step pipeline-${status}`}>
              <div className="pipeline-node">{status === "done" ? "✓" : stepIndex + 1}</div>
              <div>
                <strong>{step.label}</strong>
                <p>{activeEvent?.detail || lastEvent?.detail || (status === "idle" ? "Waiting" : "Complete")}</p>
              </div>
            </div>
          );
        })}
      </div>
      <details className="pipeline-details">
        <summary>Technical details</summary>
        <ol>
          {events.filter((event) => event.type === "stage" && event.node_name).map((event, index) => (
            <li key={`${event.node_name}-${event.status}-${index}`}>
              <strong>{event.node_name}</strong>
              <span>{event.detail || event.status || "Running"}</span>
            </li>
          ))}
        </ol>
      </details>
    </div>
  );
}
