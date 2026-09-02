"use client";

import { useState, type FormEvent } from "react";

import {
  downloadReport,
  sendReportEmail,
  sendReportWhatsApp,
  type ReportDownloadFormat,
} from "@/lib/browser-api";

import styles from "./report-actions.module.css";

type DeliveryChannel = "email" | "whatsapp";

type ReportActionsProps = {
  reportId: string;
  executiveSummary: string;
};

const DOWNLOAD_FORMATS: Array<{ format: ReportDownloadFormat; label: string }> = [
  { format: "pdf", label: "PDF" },
  { format: "docx", label: "DOCX" },
  { format: "csv", label: "CSV" },
];

function DownloadIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24">
      <path d="M12 3v11m0 0 4-4m-4 4-4-4M5 17v3h14v-3" />
    </svg>
  );
}

function SendIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24">
      <path d="m4 4 17 8-17 8 3-8-3-8Zm3 8h14" />
    </svg>
  );
}

export function ReportActions({ reportId, executiveSummary }: ReportActionsProps) {
  const [activeDownload, setActiveDownload] = useState<ReportDownloadFormat | null>(null);
  const [channel, setChannel] = useState<DeliveryChannel>("email");
  const [recipient, setRecipient] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [notice, setNotice] = useState<{ tone: "success" | "error"; message: string } | null>(null);

  async function handleDownload(format: ReportDownloadFormat) {
    setActiveDownload(format);
    setNotice(null);
    try {
      const { blob, filename } = await downloadReport(reportId, format);
      const objectUrl = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = objectUrl;
      anchor.download = filename;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(objectUrl);
      setNotice({ tone: "success", message: `${format.toUpperCase()} download is ready.` });
    } catch (error) {
      setNotice({
        tone: "error",
        message: error instanceof Error ? error.message : "The report could not be downloaded.",
      });
    } finally {
      setActiveDownload(null);
    }
  }

  async function handleDelivery(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const destination = recipient.trim();
    if (!destination) {
      setNotice({ tone: "error", message: `Enter an ${channel === "email" ? "email address" : "WhatsApp number"}.` });
      return;
    }

    setIsSending(true);
    setNotice(null);
    try {
      if (channel === "email") {
        await sendReportEmail(reportId, destination, "AuditReady AI pre-audit report");
      } else {
        await sendReportWhatsApp(reportId, destination, executiveSummary);
      }
      setNotice({
        tone: "success",
        message: channel === "email" ? "Demo email sent with the report attached." : "Demo WhatsApp summary sent.",
      });
      setRecipient("");
    } catch (error) {
      setNotice({
        tone: "error",
        message: error instanceof Error ? error.message : "The demo delivery could not be completed.",
      });
    } finally {
      setIsSending(false);
    }
  }

  function chooseChannel(nextChannel: DeliveryChannel) {
    setChannel(nextChannel);
    setRecipient("");
    setNotice(null);
  }

  return (
    <section className={styles.shell} aria-label="Report actions">
      <div className={styles.downloadPanel}>
        <div className={styles.panelHeading}>
          <span className={styles.iconBox}><DownloadIcon /></span>
          <div><strong>Download</strong></div>
        </div>
        <div className={styles.formatGrid}>
          {DOWNLOAD_FORMATS.map(({ format, label }) => (
            <button
              key={format}
              type="button"
              className={styles.formatButton}
              disabled={activeDownload !== null}
              onClick={() => void handleDownload(format)}
            >
              <strong>{activeDownload === format ? "Preparing…" : label}</strong>
            </button>
          ))}
        </div>
      </div>

      <form className={styles.deliveryPanel} onSubmit={handleDelivery}>
        <div className={styles.panelHeading}>
          <span className={`${styles.iconBox} ${styles.orangeIcon}`}><SendIcon /></span>
          <div><strong>Send copy</strong></div>
        </div>

        <div className={styles.channelSwitch} aria-label="Delivery channel">
          <button type="button" aria-pressed={channel === "email"} onClick={() => chooseChannel("email")}>Email</button>
          <button type="button" aria-pressed={channel === "whatsapp"} onClick={() => chooseChannel("whatsapp")}>WhatsApp</button>
        </div>

        <label className={styles.recipientField}>
          <span>{channel === "email" ? "Recipient email" : "WhatsApp number"}</span>
          <div>
            <input
              type={channel === "email" ? "email" : "tel"}
              inputMode={channel === "email" ? "email" : "tel"}
              value={recipient}
              onChange={(event) => setRecipient(event.target.value)}
              placeholder={channel === "email" ? "compliance@factory.pk" : "+92 300 0000000"}
              autoComplete={channel === "email" ? "email" : "tel"}
              required
            />
            <button type="submit" disabled={isSending}>
              {isSending ? "Sending…" : "Send demo"}
              {!isSending ? <SendIcon /> : null}
            </button>
          </div>
        </label>
      </form>

      {notice ? <p className={`${styles.notice} ${notice.tone === "error" ? styles.error : ""}`} aria-live="polite">{notice.message}</p> : null}
    </section>
  );
}
