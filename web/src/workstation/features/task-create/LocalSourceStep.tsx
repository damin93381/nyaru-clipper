import { ChevronLeft, Folder, HardDrive, Video } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import type { ReactNode } from "react";

import { getLocalDirectory } from "./api";

interface LocalSourceStepProps {
  readonly onSelect: (selection: LocalFileSelection) => void;
}

export interface LocalFileSelection {
  readonly name: string;
  readonly relativePath: string;
  readonly rootId: string;
}

interface BrowseLocation {
  readonly relativePath: string;
  readonly rootId: string;
}

export function LocalSourceStep({ onSelect }: LocalSourceStepProps): ReactNode {
  const [location, setLocation] = useState<BrowseLocation | null>(null);
  const catalogQuery = useQuery({
    queryKey: ["workstation", "sources", "local", location],
    queryFn: () => getLocalDirectory(location?.rootId, location?.relativePath),
  });

  if (catalogQuery.isPending) return <p className="ny-feedback ny-feedback--loading">正在读取受信任的本地媒体目录。</p>;
  if (catalogQuery.isError || catalogQuery.data === undefined) return <p className="ny-feedback ny-feedback--failure">本地媒体目录暂时不可读取。请检查工作站导入根目录。</p>;

  const catalog = catalogQuery.data;
  if (location === null) {
    return (
      <div className="ny-task-create__step" aria-label="本地导入根目录">
        <p className="ny-task-create__hint">只显示工作站配置的导入根目录；原始主机路径不会发送到浏览器。</p>
        {catalog.roots.map((root) => <button className="ny-task-create__catalog-item" key={root.id} onClick={() => setLocation({ relativePath: "", rootId: root.id })} type="button"><HardDrive aria-hidden="true" size="var(--ny-icon-default)" strokeWidth="var(--ny-icon-stroke)" />{root.name}</button>)}
      </div>
    );
  }

  return (
    <div className="ny-task-create__step" aria-label="本地媒体目录">
      <div className="ny-task-create__catalog-heading"><button className="ny-button ny-button--quiet" onClick={() => setLocation(null)} type="button"><ChevronLeft aria-hidden="true" size="var(--ny-icon-default)" strokeWidth="var(--ny-icon-stroke)" />导入根目录</button><span className="ny-task-create__hint">{catalog.relative_path || "根目录"}</span></div>
      {catalog.entries.map((entry) => entry.kind === "directory"
        ? <button className="ny-task-create__catalog-item" key={entry.relative_path} onClick={() => setLocation({ relativePath: entry.relative_path, rootId: location.rootId })} type="button"><Folder aria-hidden="true" size="var(--ny-icon-default)" strokeWidth="var(--ny-icon-stroke)" />{entry.name}</button>
        : <button className="ny-task-create__catalog-item" key={entry.relative_path} onClick={() => onSelect({ name: entry.name, relativePath: entry.relative_path, rootId: location.rootId })} type="button"><Video aria-hidden="true" size="var(--ny-icon-default)" strokeWidth="var(--ny-icon-stroke)" />{entry.name}</button>)}
    </div>
  );
}
