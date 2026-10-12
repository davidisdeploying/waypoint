import type {CertificationPackSource} from "./types";

export function sourceRefreshMessage(source: CertificationPackSource) {
  if (!source.source_url) return null;
  if (source.refresh_status === "match") {
    return "Live vendor file matches the pinned SHA-256.";
  }
  if (source.refresh_status === "drift") {
    return "Vendor file changed — review required before updating this pack.";
  }
  if (source.refresh_status === "error") {
    return "Vendor refresh check failed — the existing pin remains unchanged.";
  }
  return "Pinned source has not completed an automated refresh check yet.";
}
