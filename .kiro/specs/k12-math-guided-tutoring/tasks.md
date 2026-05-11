# 实施计划：K12 数学引导式辅导

## 概述

本计划将 K12 数学引导式辅导功能的设计分解为可增量执行的编码任务。每个任务基于前序任务构建，最终将所有组件集成到 DeepTutor 平台中。实现语言为 Python，测试使用 pytest + Hypothesis。

## Tasks

- [x] 1. 搭建项目结构与核心数据模型
  - [x] 1.1 创建 `deeptutor/k12/` 包目录结构
    - 创建 `deeptutor/k12/__init__.py`
    - 创建 `deeptutor/k12/agents/__init__.py`
    - 创建 `deeptutor/k12/agents/prompts/` 目录（含 `__init__.py`）
    - 创建 `deeptutor/k12/data/__init__.py` 和 `deeptutor/k12/data/README.md`（数据格式说明）
    - _Requirements: 6.3_

  - [x] 1.2 实现领域数据模型 `deeptutor/k12/models.py`
    - 使用 Pydantic 定义 `KnowledgePoint`、`ExampleTemplate`、`CompletionType`、`MasteryRecord`、`StudentProfileData`、`LearningReport`、`PracticeProblem`、`SolvingSessionState` 等模型
    - 确保 `MasteryRecord.score` 字段约束为 [0.0, 1.0]，`KnowledgePoint.difficulty` 约束为 [1, 5]
    - _Requirements: 5.1, 5.3, 5.4, 6.1, 7.5, 8.1_

  - [x] 1.3 编写数据模型的属性测试
    - **Property 12: 解题状态序列化往返一致性**
    - **Validates: Requirements 8.2**

  - [x] 1.4 编写数据模型的单元测试
    - 测试 `KnowledgePoint` 字段验证（difficulty 范围、必填字段）
    - 测试 `MasteryRecord` score 边界约束
    - 测试 `SolvingSessionState` JSON 序列化/反序列化
    - _Requirements: 5.4, 6.1, 8.1_

- [x] 2. 实现知识图谱模块
  - [x] 2.1 实现 `deeptutor/k12/knowledge_graph.py`
    - 实现 `KnowledgeGraph` 类：`load()`、`get_point()`、`get_prerequisites_chain()`、`topological_sort()`、`get_weak_points()`、`is_dag()` 方法
    - 从 `deeptutor/k12/data/` 目录动态加载 JSON 数据文件
    - 实现拓扑排序算法（Kahn's algorithm 或 DFS）
    - 实现依赖链的递归/迭代检索
    - _Requirements: 6.2, 6.3, 6.4, 6.6_

  - [x] 2.2 创建示例知识图谱数据文件
    - 创建 `deeptutor/k12/data/example_grade7_semester1.json`，包含至少 5 个知识点及其前置依赖关系和示例题目模板
    - 确保数据格式符合设计文档中定义的 JSON schema
    - _Requirements: 6.1, 6.3, 6.5_

  - [x] 2.3 编写知识图谱 DAG 验证属性测试
    - **Property 7: 知识图谱为有向无环图**
    - **Validates: Requirements 6.2**

  - [x] 2.4 编写拓扑排序属性测试
    - **Property 1: 知识点拓扑排序保持依赖序**
    - **Validates: Requirements 2.4**

  - [x] 2.5 编写依赖链完整性属性测试
    - **Property 8: 依赖链包含所有传递前置知识点**
    - **Validates: Requirements 6.4**

  - [x] 2.6 编写知识图谱单元测试
    - 测试加载有效/无效 JSON 文件
    - 测试空图、单节点图、多节点图的拓扑排序
    - 测试环检测
    - _Requirements: 6.2, 6.3, 6.4_

- [x] 3. 实现学生画像模块
  - [x] 3.1 实现 `deeptutor/k12/student_profile.py`
    - 实现 `StudentProfile` 类：`create_profile()`、`load_profile()`、`save_profile()`、`update_mastery()`、`get_learning_report()` 方法
    - 持久化使用 JSON 文件存储（存储目录可配置）
    - `update_mastery` 实现增量规则：INDEPENDENT +0.15, GUIDED +0.08, FAILED -0.05
    - 结果 clamp 到 [0.0, 1.0]
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

  - [x] 3.2 编写掌握度更新属性测试
    - **Property 5: 掌握度更新公式与边界约束**
    - **Validates: Requirements 5.3, 5.4**

  - [x] 3.3 编写学生画像持久化属性测试
    - **Property 4: 学生画像持久化往返一致性**
    - **Validates: Requirements 5.2**

  - [x] 3.4 编写学习报告属性测试
    - **Property 6: 学习报告按掌握度升序排列且正确标记薄弱项**
    - **Validates: Requirements 5.5**

  - [x] 3.5 编写学生画像单元测试
    - 测试新建画像初始化所有 mastery 为 0.0
    - 测试边界情况：mastery 从 0.0 减少不低于 0.0，从 0.95 增加不超过 1.0
    - 测试学习报告排序和薄弱项标记
    - _Requirements: 5.1, 5.3, 5.4, 5.5_

- [x] 4. Checkpoint - 确保所有测试通过
  - 确保所有测试通过，ask the user if questions arise.

- [x] 5. 实现苏格拉底式引导引擎
  - [x] 5.1 创建引导提示词模板 `deeptutor/k12/agents/prompts/guide.py`
    - 定义 full/moderate/minimal 三个级别的系统提示词
    - 定义引导问题生成的 prompt 模板
    - 定义错误反馈的 prompt 模板（不含答案）
    - _Requirements: 3.2, 3.3, 3.4, 3.7_

  - [x] 5.2 实现 `deeptutor/k12/agents/socratic_guide.py`
    - 实现 `SocraticGuide` 类：`determine_guidance_level()`、`generate_steps()`、`provide_guidance()`、`downgrade_guidance()` 方法
    - `determine_guidance_level`: 平均 mastery < 0.4 → full, 0.4-0.7 → moderate, > 0.7 → minimal
    - `provide_guidance`: 处理学生回答，正确则推进，错误则 error_count++，连续 3 次错误降级
    - 通过 StreamBus 的 content 方法输出引导问题
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7_

  - [x] 5.3 编写引导等级映射属性测试
    - **Property 2: 掌握度到引导等级的映射正确性**
    - **Validates: Requirements 3.1**

  - [x] 5.4 编写连续错误降级属性测试
    - **Property 3: 连续错误触发引导等级降低**
    - **Validates: Requirements 3.6**

  - [x] 5.5 编写苏格拉底引导单元测试
    - 测试 full 级别输出细粒度步骤和知识点提示
    - 测试 moderate 级别仅关键转折点提问
    - 测试 minimal 级别仅在请求时提供提示
    - 测试连续 3 次错误后降级行为
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.6_

- [x] 6. 实现题目分析器与答案验证器
  - [x] 6.1 创建分析提示词模板 `deeptutor/k12/agents/prompts/analyze.py`
    - 定义题目分析的系统提示词（识别知识点、估计难度、规划步骤）
    - 定义图片信息提取的 prompt 模板
    - _Requirements: 2.1, 2.2_

  - [x] 6.2 实现 `deeptutor/k12/agents/problem_analyzer.py`
    - 实现 `ProblemAnalyzer` 类和 `AnalysisResult` 数据类
    - `analyze()` 方法：解析题目文本/图片 → LLM 识别知识点 → RAG 检索教学内容 → 按依赖序排列
    - 通过 StreamBus 发送 progress 事件报告分析进度
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5_

  - [x] 6.3 创建验证提示词模板 `deeptutor/k12/agents/prompts/validate.py`
    - 定义代码生成验证的 prompt 模板
    - 定义 LLM fallback 验证的 prompt 模板
    - _Requirements: 4.1, 4.4_

  - [x] 6.4 实现 `deeptutor/k12/agents/answer_validator.py`
    - 实现 `AnswerValidator` 类和 `ValidationResult` 数据类
    - `validate()` 方法：生成验证代码 → Code_Execution_Tool 执行 → 超时/失败回退 LLM
    - 通过 StreamBus 发送 tool_call 和 tool_result 事件
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5_

  - [x] 6.5 编写题目分析器和答案验证器单元测试
    - 测试图片附件题目分析流程
    - 测试 Code_Execution 超时回退到 LLM fallback
    - 测试正确答案确认和错误答案提示（不含答案）
    - _Requirements: 2.1, 2.2, 4.1, 4.4_

- [x] 7. 实现解题总结器
  - [x] 7.1 创建总结提示词模板 `deeptutor/k12/agents/prompts/summarize.py`
    - 定义解题总结生成的 prompt 模板（包含路径回顾、知识点列表、易错点）
    - _Requirements: 9.1, 9.2_

  - [x] 7.2 实现 `deeptutor/k12/agents/solve_summarizer.py`
    - 实现 `SolveSummarizer` 类和 `SolveSummary` 数据类
    - `summarize()` 方法：回顾解题路径 → 标注需引导步骤 → 计算 mastery 更新 → 更新 StudentProfile
    - 通过 StreamBus 的 result 事件发送结构化结果
    - _Requirements: 9.1, 9.2, 9.3, 9.4_

  - [x] 7.3 编写解题总结属性测试
    - **Property 13: 解题总结包含所有必要信息**
    - **Validates: Requirements 9.1, 9.2, 9.3**

  - [x] 7.4 编写解题总结单元测试
    - 测试完成解题后总结包含所有必要字段
    - 测试 steps_needing_help 正确反映非独立完成步骤
    - _Requirements: 9.1, 9.2, 9.3_

- [x] 8. Checkpoint - 确保所有测试通过
  - 确保所有测试通过，ask the user if questions arise.

- [x] 9. 实现自适应练习生成器
  - [x] 9.1 实现 `deeptutor/k12/practice_generator.py`
    - 实现 `PracticeGenerator` 类：`generate_practice_set()`、`select_knowledge_points()`、`adjust_difficulty()`、`validate_answer()` 方法
    - 练习题集比例：70% 薄弱、20% 复习、10% 挑战
    - 难度调整：连续 3 次正确 +1，连续 2 次错误 -1，范围 [1, 5]
    - 使用 Code_Execution_Tool 验证参考答案正确性
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6_

  - [x] 9.2 编写练习题集分布比例属性测试
    - **Property 9: 练习题集分布比例正确**
    - **Validates: Requirements 7.1**

  - [x] 9.3 编写难度调整属性测试
    - **Property 10: 难度调整遵循连续答题规则**
    - **Validates: Requirements 7.3, 7.4**

  - [x] 9.4 编写练习题结构完整性属性测试
    - **Property 11: 练习题结构完整性**
    - **Validates: Requirements 7.5**

  - [x] 9.5 编写练习生成器单元测试
    - 测试空薄弱知识点时的降级行为
    - 测试难度边界（不低于 1，不高于 5）
    - 测试验证失败的题目被丢弃
    - _Requirements: 7.1, 7.3, 7.4, 7.6_

- [x] 10. 实现 Capability 入口与注册
  - [x] 10.1 实现 `deeptutor/capabilities/guided_solve.py`
    - 实现 `GuidedSolveCapability` 类，继承 `BaseCapability`
    - 定义 `CapabilityManifest`：name="guided_solve", stages=["analyzing", "guiding", "validating", "summarizing"], tools_used=["rag", "code_execution"], cli_aliases=["guided_solve", "tutor"]
    - 实现 `run()` 方法编排四阶段流程：analyzing → guiding → validating → summarizing
    - 在 metadata 中维护 `SolvingSessionState`，支持多轮对话状态恢复
    - 通过 StreamBus 的 stage 上下文管理器标记阶段开始/结束
    - 处理放弃题目的情况（保存进度、更新 mastery）
    - 流程完成时发送 DONE 类型 StreamEvent
    - _Requirements: 1.1, 1.3, 1.4, 1.5, 8.1, 8.2, 8.3, 8.4, 8.5, 10.1, 10.2, 10.3, 10.4, 10.5_

  - [x] 10.2 在 `deeptutor/runtime/bootstrap/builtin_capabilities.py` 中注册 guided_solve
    - 添加 `"guided_solve": "deeptutor.capabilities.guided_solve:GuidedSolveCapability"` 到 `BUILTIN_CAPABILITY_CLASSES`
    - _Requirements: 1.2_

  - [x] 10.3 编写进度事件属性测试
    - **Property 14: 进度事件包含正确的步骤信息**
    - **Validates: Requirements 10.4**

  - [x] 10.4 编写 Capability 集成单元测试
    - 测试 ChatOrchestrator 路由 active_capability="guided_solve" 到 GuidedSolveCapability
    - 测试 StreamBus 事件序列（STAGE_START/END、content、progress、DONE）
    - 测试多轮对话状态恢复
    - 测试放弃题目流程
    - _Requirements: 1.2, 1.3, 8.2, 8.4, 10.1, 10.5_

- [x] 11. 端到端集成与连接
  - [x] 11.1 连接所有组件并实现完整解题流程
    - 确保 `GuidedSolveCapability.run()` 正确实例化并调用 ProblemAnalyzer、SocraticGuide、AnswerValidator、SolveSummarizer
    - 确保 KnowledgeGraph 和 StudentProfile 在 Capability 初始化时正确加载
    - 确保 RAG_Tool 和 Code_Execution_Tool 通过现有 ToolRegistry 获取
    - 处理所有错误场景（RAG 失败、Code_Execution 超时、画像加载失败等）
    - _Requirements: 1.1, 2.3, 4.4, 8.2, 10.1, 10.5_

  - [x] 11.2 编写端到端集成测试
    - 测试完整解题流程：分析 → 引导 → 验证 → 总结
    - 测试 RAG 检索集成
    - 测试多轮对话状态恢复
    - 使用 mock 替代实际 LLM 调用
    - _Requirements: 1.3, 2.3, 8.2_

- [x] 12. Final checkpoint - 确保所有测试通过
  - 确保所有测试通过，ask the user if questions arise.

## Notes

- 标记 `*` 的任务为可选任务，可跳过以加速 MVP 交付
- 每个任务引用了具体的需求编号以确保可追溯性
- Checkpoint 任务确保增量验证
- 属性测试使用 Hypothesis 库验证通用正确性属性
- 单元测试验证具体示例和边界情况
- 所有 LLM 调用在测试中使用 mock，不依赖外部服务
- 知识图谱数据文件为示例数据，实际教学内容后续由课程团队补充
