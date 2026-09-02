"use client";

import { FormEvent, useRef, useState } from "react";

type GuideMessage = { question: string; answer: string };
type GuideTopic = { keywords: string[]; answer: string };

const topics: GuideTopic[] = [
  { keywords: ["feature", "features", "product", "do", "help", "about", "purpose"], answer: "AuditReady AI helps textile and leather teams prepare for buyer audits. Add supplier evidence, ask questions in plain language, see the proof behind a finding, and share a clear readiness report." },
  { keywords: ["account", "signup", "sign", "register", "login", "create", "start", "workspace"], answer: "Select Create account or sign in to access the workspace. Your projects, files, and conversations stay in your own workspace. Admin accounts have an additional verification step." },
  { keywords: ["security", "secure", "privacy", "data", "safe", "hack", "protect"], answer: "Your workspace is protected with signed sessions, role based access, protected routes, multi factor authentication for admins, and an audit trail. Project files and chat data stay inside the signed in workspace." },
  { keywords: ["audit", "replace", "replacement", "auditor", "real", "onsite"], answer: "AuditReady is a preparation assistant, not a replacement for a real audit. A real audit still needs worker interviews, payroll verification, and professional on site judgement." },
  { keywords: ["follow", "history", "session", "after", "continue", "conversation"], answer: "Yes. After an upload, your project keeps the conversation, files, and latest report together so your team can ask follow up questions in context." },
  { keywords: ["policy", "policies", "procedure", "record", "before", "upload", "document", "file"], answer: "Yes. Add supplier policies, procedures, wage records, training documents, or other evidence before asking a question. AuditReady uses that project context in its response." },
  { keywords: ["web", "search", "internet", "current", "latest", "live"], answer: "When a question needs current information, the audit workspace can use DuckDuckGo through a controlled tool connection. It shows the search step and the sources used in the answer." },
  { keywords: ["mcp", "gmail", "whatsapp", "integration", "tool"], answer: "MCP lets AuditReady use helpful tools. This demonstration includes web search, document utilities, calculators, and safe dummy Gmail and WhatsApp services. It never accesses a personal Gmail or WhatsApp account." },
  { keywords: ["rag", "citation", "source", "proof", "evidence", "grounded"], answer: "For audit questions, AuditReady checks your project files and trusted knowledge, ranks the most relevant evidence, and provides citations when it has enough support for an answer." },
];

const quickQuestions = ["What can AuditReady AI do?", "How is my data protected?", "Is this a replacement for a real audit?", "Can I add policies before asking a question?"];

function words(value: string) {
  return new Set(value.toLowerCase().replace(/[^a-z0-9 ]/g, " ").split(/\s+/).filter((word) => word.length > 2));
}

function answerFor(question: string) {
  const queryWords = words(question);
  const best = topics.reduce<{ topic: GuideTopic; score: number } | null>((current, topic) => {
    const score = topic.keywords.reduce((total, keyword) => total + (queryWords.has(keyword) ? 1 : 0), 0);
    return !current || score > current.score ? { topic, score } : current;
  }, null);
  return best && best.score > 0 ? best.topic.answer : "I can help with AuditReady AI, account access, data security, evidence uploads, audit preparation, web search, and tool integrations. Ask your question in your own words and I will guide you to the right part of the product.";
}

export function ProductGuide() {
  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState<GuideMessage[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);

  function ask(value: string) {
    const cleanValue = value.trim();
    if (!cleanValue) return;
    setMessages((current) => [...current, { question: cleanValue, answer: answerFor(cleanValue) }]);
    setQuestion("");
    requestAnimationFrame(() => inputRef.current?.focus());
  }

  function submit(event: FormEvent<HTMLFormElement>) { event.preventDefault(); ask(question); }

  return <div className="product-guide"><form className="mkt-ask-box" onSubmit={submit}><input ref={inputRef} aria-label="Ask about AuditReady AI" onChange={(event) => setQuestion(event.target.value)} placeholder="Ask about AuditReady, accounts, security, or audit preparation" value={question} /><button type="submit">Ask AuditReady</button></form><div className="guide-prompts">{quickQuestions.map((prompt) => <button key={prompt} type="button" onClick={() => ask(prompt)}>{prompt}</button>)}</div>{messages.length ? <div className="product-guide-thread" aria-live="polite">{messages.map((message, index) => <div className="product-guide-answer" key={`${message.question}-${index}`}><span className="product-guide-question">You asked: {message.question}</span><strong>AuditReady AI</strong><p>{message.answer}</p></div>)}</div> : <p className="helper">Ask in your own words, or choose a common question to get started.</p>}</div>;
}
