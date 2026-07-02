// These labels currently come from backend display text. Stable backend series IDs
// would be less fragile and should replace label matching in a future API revision.
export const SERIES_LABELS = {
  volumes: {
    delivered: "Delivered volume",
    nominated: "Nominated volume",
  },
  revenue: {
    epex: "EPEX revenue",
    imbalance: "Total imbalance revenue",
    total: "Total revenue",
  },
  prices: {
    epex: "EPEX price",
    longImbalance: "Long imbalance price",
    shortImbalance: "Short imbalance price",
  },
};
