// 命令的参数与返回类型由命令目录生成（generated.ts，ROADMAP L2）；这里只放从它派生的别名。
import type { JobSummary, RhythmRendered, SampleRow, SubtitleRow } from "./generated";

export type * from "./generated";

export type Nature = SampleRow["nature"];
export type JobStatus = JobSummary["status"];
export type SubtitleRowStatus = SubtitleRow["status"];
export type RhythmPlan = NonNullable<RhythmRendered["plan"]>;
export type RhythmSound = RhythmRendered["sound"];
