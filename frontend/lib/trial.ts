// Question-based "Start for Free" trial tracking.
//
// Guests (non-logged-in users) get 3 free questions, enforced server-side in the
// usage quota engine (app/core/quota.py). The client reads the real remaining
// count from GET /usage so it always matches what the backend will allow, and
// the banner updates after every answered question.

import type { UsageSnapshot } from "./api";

export const TRIAL_QUESTIONS = 3;

export interface TrialStatus {
  active: boolean;
  remaining: number;
  used: number;
  limit: number;
  questionsLimit: number;
  /** 0 → 100, how much of the trial allocation has been used. */
  percentUsed: number;
  expired: boolean;
}

/** Build a trial status from the server-reported usage snapshot. */
export function trialStatusFromUsage(usage: UsageSnapshot): TrialStatus {
  const limit = usage.trial?.questions_limit ?? TRIAL_QUESTIONS;
  const remaining = usage.trial?.questions_remaining ?? 0;
  const used = Math.max(limit - remaining, 0);
  const expired = remaining <= 0;
  return {
    active: !expired,
    remaining: Math.max(remaining, 0),
    limit,
    questionsLimit: limit,
    used,
    percentUsed: limit > 0 ? Math.min(100, Math.round((used / limit) * 100)) : 100,
    expired,
  };
}

/** Human readable remaining, e.g. "2 questions left" or "Trial ended". */
export function formatTrialRemaining(status: TrialStatus): string {
  if (status.expired) return "Trial ended · sign in to continue";
  return `${status.remaining} question${status.remaining === 1 ? "" : "s"} left`;
}