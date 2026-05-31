import { useEffect } from "react";

export function usePageTitle(title: string) {
  useEffect(() => {
    document.title = title ? `${title} — H.265 Transcoder` : "H.265 Transcoder";
    return () => { document.title = "H.265 Transcoder"; };
  }, [title]);
}
