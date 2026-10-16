import { useTranslation } from "react-i18next";
import "./MarketplaceInstallProgress.css";

export type InstallationProgress = {
  status: string;
  stage?: string;
  size_bytes?: number;
  downloaded_bytes?: number;
  elapsed_seconds?: number;
  current_dependency?: string;
};

function bytes(value: number) {
  if (value < 1024) return `${Math.floor(value)} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

export function MarketplaceInstallProgress({ job }: { job: InstallationProgress }) {
  const { t } = useTranslation();
  const total = job.size_bytes;
  const received = job.downloaded_bytes;
  const measured = job.status === "downloading"
    && typeof total === "number" && Number.isFinite(total) && total > 0
    && typeof received === "number" && Number.isFinite(received) && received >= 0;
  const downloaded = measured ? Math.min(received, total) : 0;
  const percent = measured ? Math.floor(100 * downloaded / total) : undefined;
  const label = t(`marketplaceInstall.stages.${job.stage || job.status}`, {
    defaultValue: t(`marketplaceInstall.status.${job.status}`),
  });
  const elapsed = Math.max(0, Math.floor(job.elapsed_seconds || 0));
  const duration = `${Math.floor(elapsed / 60)}:${String(elapsed % 60).padStart(2, "0")}`;

  return <div className="space-y-2">
    <div className="flex items-center justify-between gap-3 text-sm">
      <span role="status">{label}</span>
      {measured && <span className="shrink-0 tabular-nums">{percent}%</span>}
    </div>
    <div role="progressbar" aria-label={label} aria-valuemin={0} aria-valuemax={100}
      aria-valuenow={percent} className="h-2 overflow-hidden rounded-full bg-muted">
      <div className={measured
        ? "h-full rounded-full bg-blue-600 transition-[width] duration-300 motion-reduce:transition-none"
        : "marketplace-install-indeterminate h-full rounded-full bg-blue-600"}
        style={measured ? { width: `${percent}%` } : undefined} />
    </div>
    {job.current_dependency && <p className="break-words text-xs text-muted-foreground">
      {t("marketplaceInstall.currentDependency", { name: job.current_dependency })}
    </p>}
    <div className="flex flex-wrap justify-between gap-x-3 text-xs tabular-nums text-muted-foreground">
      {measured && <span>{bytes(downloaded)} / {bytes(total)}</span>}
      {typeof job.elapsed_seconds === "number" && <span>{t("marketplaceInstall.elapsed", { time: duration })}</span>}
    </div>
  </div>;
}
