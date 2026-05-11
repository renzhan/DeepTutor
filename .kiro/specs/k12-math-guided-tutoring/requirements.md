# 需求文档：K12 数学引导式辅导 (Guided Tutoring)

## 简介

本功能为 DeepTutor 平台新增一个 K12 数学引导式辅导能力（Capability），面向中国初中学生（七至九年级）。系统采用苏格拉底式提问法，引导学生自主解题而非直接给出答案，同时跟踪学生知识点掌握情况并生成针对性练习。具体覆盖的年级和教材版本由知识库内容决定，代码层面不硬编码特定年级或教材。

## 术语表

- **Guided_Solve_Capability**: 引导式解题能力插件，作为 DeepTutor BaseCapability 的子类实现，负责整个引导式辅导流程的编排
- **Knowledge_Graph**: 知识图谱模块，存储课标对齐的知识点结构，包含知识点之间的前置依赖关系和难度等级。具体内容由知识库数据驱动，代码不绑定特定年级
- **Student_Profile**: 学生画像模块，记录学生的年级、学期、教材版本以及各知识点的掌握度
- **Mastery_Score**: 掌握度评分，取值范围 0.0 到 1.0 的浮点数，表示学生对某个知识点的掌握程度
- **Socratic_Guide**: 苏格拉底式引导引擎，根据学生掌握度和题目难度生成分层提示问题
- **Practice_Generator**: 自适应练习生成器，根据学生薄弱知识点生成针对性练习题
- **Guidance_Level**: 引导等级，分为 full（完整引导）、moderate（适度引导）、minimal（最少引导）三级
- **StreamBus**: DeepTutor 的异步事件流通道，用于向前端推送实时进度
- **UnifiedContext**: DeepTutor 的统一上下文数据对象，承载用户消息、会话历史、工具配置等信息
- **Code_Execution_Tool**: DeepTutor 内置的代码执行工具，用于运行 Python 代码验证数学计算结果
- **RAG_Tool**: DeepTutor 内置的检索增强生成工具，用于从教材知识库中检索相关内容

## 需求

### 需求 1：引导式解题能力注册

**用户故事：** 作为 DeepTutor 平台管理员，我希望引导式辅导作为标准 Capability 注册到系统中，以便学生可以通过 CLI、WebSocket 和 SDK 访问该功能。

#### 验收标准

1. THE Guided_Solve_Capability SHALL 继承 BaseCapability 并提供包含 name、description、stages、tools_used 和 cli_aliases 字段的 CapabilityManifest
2. THE Guided_Solve_Capability SHALL 在 BUILTIN_CAPABILITY_CLASSES 注册表中以 "guided_solve" 为键注册
3. WHEN ChatOrchestrator 接收到 active_capability 为 "guided_solve" 的 UnifiedContext 时，THE ChatOrchestrator SHALL 将请求路由到 Guided_Solve_Capability
4. THE Guided_Solve_Capability SHALL 定义 stages 为 ["analyzing", "guiding", "validating", "summarizing"]
5. THE Guided_Solve_Capability SHALL 声明 tools_used 为 ["rag", "code_execution"]

### 需求 2：题目分析与知识点识别

**用户故事：** 作为学生，我希望输入一道数学题后系统能自动识别涉及的知识点，以便系统提供针对性的引导。

#### 验收标准

1. WHEN 学生提交一道数学题（文本形式）时，THE Guided_Solve_Capability SHALL 在 "analyzing" 阶段解析题目并识别出所有相关知识点
2. WHEN 学生提交包含图片附件的数学题时，THE Guided_Solve_Capability SHALL 提取图片中的数学信息并结合文本进行分析
3. THE Guided_Solve_Capability SHALL 通过 RAG_Tool 从教材知识库中检索与识别到的知识点相关的教学内容
4. WHEN 题目涉及多个知识点时，THE Guided_Solve_Capability SHALL 按照 Knowledge_Graph 中定义的前置依赖顺序排列知识点
5. THE Guided_Solve_Capability SHALL 通过 StreamBus 发送 progress 事件，报告题目分析的进度和识别到的知识点列表

### 需求 3：苏格拉底式分层引导

**用户故事：** 作为学生，我希望系统通过提问引导我自己解出答案，而不是直接告诉我答案，以便我真正理解解题思路。

#### 验收标准

1. THE Socratic_Guide SHALL 根据学生对相关知识点的 Mastery_Score 确定 Guidance_Level：Mastery_Score 低于 0.4 使用 full 级别，0.4 到 0.7 使用 moderate 级别，高于 0.7 使用 minimal 级别
2. WHILE Guidance_Level 为 full 时，THE Socratic_Guide SHALL 将解题过程分解为细粒度步骤，每步提供一个引导性问题和必要的知识点提示
3. WHILE Guidance_Level 为 moderate 时，THE Socratic_Guide SHALL 提供关键转折点的引导性问题，省略基础步骤的提示
4. WHILE Guidance_Level 为 minimal 时，THE Socratic_Guide SHALL 仅在学生明确请求帮助时提供方向性提示
5. THE Socratic_Guide SHALL 在每轮对话中等待学生回答后再提供下一步引导，通过 StreamBus 的 content 事件输出引导问题
6. IF 学生连续三次回答错误同一步骤，THEN THE Socratic_Guide SHALL 降低当前步骤的引导等级并提供更详细的提示
7. THE Socratic_Guide SHALL 在整个引导过程中避免直接展示最终答案，仅在学生自行得出正确答案后进行确认

### 需求 4：答案验证

**用户故事：** 作为学生，我希望系统能准确判断我的答案是否正确，以便我知道自己的解题是否成功。

#### 验收标准

1. WHEN 学生提交一个解题步骤的答案时，THE Guided_Solve_Capability SHALL 使用 Code_Execution_Tool 执行 Python 代码验证该答案的数学正确性
2. WHEN 验证结果为正确时，THE Guided_Solve_Capability SHALL 通过 StreamBus 发送确认消息并引导进入下一步骤
3. WHEN 验证结果为错误时，THE Guided_Solve_Capability SHALL 通过 StreamBus 发送提示消息，指出错误方向但不直接给出正确答案
4. IF Code_Execution_Tool 执行超时或失败，THEN THE Guided_Solve_Capability SHALL 回退到 LLM 推理验证并记录验证方式为 "llm_fallback"
5. THE Guided_Solve_Capability SHALL 在 "validating" 阶段通过 StreamBus 发送 tool_call 和 tool_result 事件，使验证过程对前端可见

### 需求 5：学生画像管理

**用户故事：** 作为学生，我希望系统记住我的学习进度和掌握情况，以便每次使用时都能获得个性化的辅导体验。

#### 验收标准

1. WHEN 新学生首次使用系统时，THE Student_Profile SHALL 创建包含年级（grade）、学期（semester）、教材版本（textbook_version）的学生记录，并将所有知识点的 Mastery_Score 初始化为 0.0
2. THE Student_Profile SHALL 将学生数据持久化存储，确保跨会话保持学习进度
3. WHEN 学生成功完成一道题目的引导式解题时，THE Student_Profile SHALL 根据解题表现更新相关知识点的 Mastery_Score：独立完成加 0.15，需要引导完成加 0.08，未能完成减 0.05
4. THE Student_Profile SHALL 将 Mastery_Score 限制在 0.0 到 1.0 的范围内
5. WHEN 请求学生学习报告时，THE Student_Profile SHALL 返回按 Mastery_Score 升序排列的知识点列表，标识出 Mastery_Score 低于 0.4 的知识点为薄弱项

### 需求 6：知识图谱结构

**用户故事：** 作为课程设计者，我希望系统的知识结构能灵活支持初中各年级数学课标，以便学生的学习路径符合教学大纲。

#### 验收标准

1. THE Knowledge_Graph SHALL 定义通用的知识点数据结构，每个知识点具有唯一标识符（id）、名称（name）、年级（grade）、学期（semester）、所属章节（chapter）、难度等级（difficulty: 1-5）和常见错误（common_mistakes）字段
2. THE Knowledge_Graph SHALL 为每个知识点定义前置知识点依赖关系（prerequisites），形成有向无环图结构
3. THE Knowledge_Graph SHALL 以 JSON 格式存储在 `deeptutor/k12/data/` 目录下，支持按年级和学期动态加载，代码不硬编码特定年级的知识点内容
4. WHEN 查询某个知识点时，THE Knowledge_Graph SHALL 返回该知识点及其所有前置知识点的完整依赖链
5. THE Knowledge_Graph SHALL 为每个知识点提供至少三个示例题目模板（example_templates），用于练习生成
6. THE Knowledge_Graph SHALL 支持通过新增 JSON 数据文件扩展到新的年级或教材版本，无需修改代码

### 需求 7：自适应练习生成

**用户故事：** 作为学生，我希望系统根据我的薄弱环节生成针对性练习，以便我能高效地提升数学能力。

#### 验收标准

1. WHEN 学生请求练习时，THE Practice_Generator SHALL 按照 70% 薄弱知识点、20% 复习巩固、10% 挑战提升的比例生成练习题集
2. THE Practice_Generator SHALL 从 Knowledge_Graph 的 example_templates 中选取题目模板，并通过 LLM 生成具体数值和情境变体
3. WHILE 学生连续正确完成三道同一知识点的练习题时，THE Practice_Generator SHALL 将该知识点的练习难度提升一个等级
4. WHILE 学生连续错误两道同一知识点的练习题时，THE Practice_Generator SHALL 将该知识点的练习难度降低一个等级并增加该知识点的练习比例
5. THE Practice_Generator SHALL 确保生成的每道练习题包含题目文本（problem_text）、涉及知识点（knowledge_points）、难度等级（difficulty）和参考答案（reference_answer）字段
6. THE Practice_Generator SHALL 使用 Code_Execution_Tool 验证生成题目的参考答案的数学正确性，丢弃验证失败的题目

### 需求 8：多轮对话状态管理

**用户故事：** 作为学生，我希望在一次解题过程中可以多轮对话，系统能记住当前解题进度，以便我可以分步骤完成复杂题目。

#### 验收标准

1. THE Guided_Solve_Capability SHALL 在 UnifiedContext 的 metadata 中维护当前解题会话的状态，包括当前步骤索引（current_step）、已完成步骤（completed_steps）和错误计数（error_count）
2. WHEN 学生在解题过程中发送新消息时，THE Guided_Solve_Capability SHALL 从 conversation_history 恢复解题上下文并继续当前步骤的引导
3. WHEN 学生完成所有解题步骤时，THE Guided_Solve_Capability SHALL 进入 "summarizing" 阶段，输出解题总结和知识点回顾
4. IF 学生在解题过程中请求放弃当前题目，THEN THE Guided_Solve_Capability SHALL 保存当前进度、更新 Mastery_Score（标记为未完成）并结束当前解题会话
5. THE Guided_Solve_Capability SHALL 通过 StreamBus 的 stage 上下文管理器标记每个阶段的开始和结束

### 需求 9：解题总结与知识点回顾

**用户故事：** 作为学生，我希望完成解题后能看到总结和知识点回顾，以便巩固学习成果。

#### 验收标准

1. WHEN 学生成功完成一道题目的所有步骤时，THE Guided_Solve_Capability SHALL 在 "summarizing" 阶段生成包含解题路径回顾、涉及知识点列表和易错点提醒的总结
2. THE Guided_Solve_Capability SHALL 在总结中标注学生在哪些步骤需要了引导帮助，作为后续复习的重点
3. THE Guided_Solve_Capability SHALL 通过 StreamBus 的 result 事件发送结构化的解题结果，包含 response（总结文本）、knowledge_points（涉及知识点）和 mastery_updates（掌握度变化）字段
4. WHEN 总结生成完成时，THE Guided_Solve_Capability SHALL 调用 Student_Profile 更新相关知识点的 Mastery_Score

### 需求 10：流式输出与前端集成

**用户故事：** 作为前端开发者，我希望引导式辅导的每个阶段都通过标准 StreamBus 事件输出，以便前端能实时展示辅导进度。

#### 验收标准

1. THE Guided_Solve_Capability SHALL 在每个 stage 转换时通过 StreamBus 发送 STAGE_START 和 STAGE_END 事件
2. THE Guided_Solve_Capability SHALL 通过 StreamBus 的 content 方法流式输出引导问题和反馈文本
3. THE Guided_Solve_Capability SHALL 通过 StreamBus 的 thinking 方法输出内部分析推理过程（对前端可选展示）
4. THE Guided_Solve_Capability SHALL 通过 StreamBus 的 progress 方法报告当前解题进度，包含 current_step 和 total_steps 信息
5. WHEN 解题流程完成时，THE Guided_Solve_Capability SHALL 发送 DONE 类型的 StreamEvent，确保前端正确关闭流式连接
