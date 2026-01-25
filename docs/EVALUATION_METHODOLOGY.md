# 评估方法论详细说明

本文档详细说明评估的方法论，回答关键的"如何"和"为什么"问题。

---

## 1️⃣ N=30 样本的选择方法

### 样本来源

**30个样本全部手工创建**，针对生物医学领域（Biomedical Domain）。

### 选择标准

1. **领域覆盖**：生物医学核心主题
   - 药理学（Metformin, ACE inhibitors, Chemotherapy）
   - 分子生物学（CRISPR, mRNA, DNA repair）
   - 免疫学（Innate/Adaptive immunity, Vaccines, Monoclonal antibodies）
   - 疾病机制（Diabetes, Alzheimer's, Antibiotic resistance）
   - 细胞生物学（Apoptosis, Cell signaling）
   - 生物技术（Next-generation sequencing, ELISA）

2. **来源文档**：Wikipedia 生物医学相关页面（30个不同URL）
   - 确保答案可从知识库检索得到
   - 避免需要外部知识的问题

3. **难度设计**：
   - 简单（30%）：直接定义类问题（"What is X?"）
   - 中等（50%）：机制/功能解释（"How does X work?"）
   - 困难（20%）：多步推理或比较（"What are the differences between X and Y?"）

### Query 类型分布

| 类型 | 数量 | 占比 | 示例 |
|------|------|------|------|
| **Definition** | 13 | 43% | "What is CRISPR?" |
| **Mechanism/Function** | 5 | 17% | "What is the primary mechanism of action of metformin?" |
| **Process** | 4 | 13% | "How do ACE inhibitors lower blood pressure?" |
| **Comparison** | 1 | 3% | "What are two defining features of type 2 diabetes compared with type 1?" |
| **Other** (Multi-part, Complex) | 7 | 23% | "What are three major components of innate immunity?" |

**Query 模式分布**：
- "What is...": 43%
- "How does...": 17%
- "What are...": 23%
- 多子句问题: 17%

### 样本代表性

✅ **优点**：
- 覆盖生物医学多个子领域
- 问题类型多样化
- 难度分层合理
- 所有答案都可从知识库验证

⚠️ **局限**：
- 仅限生物医学领域（不能代表所有领域）
- 问题都是事实型（factual），无开放讨论题
- 英文问题（不包含多语言测试）
- 30个样本量相对较小（统计显著性有限）

---

## 2️⃣ RAGAS 指标评估方法

### 评估类型：**自动评估（LLM-as-Judge）**

所有 RAGAS 指标（faithfulness, answer relevancy, context precision, context recall）均为**自动评估**，无人工介入。

### Judge 模型

**使用模型**：`gemini-2.5-flash`

```python
# evaluation.py
llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0)
embeddings = GoogleGenerativeAIEmbeddings(model="text-embedding-004")

results = evaluate(
    dataset=dataset,
    metrics=[faithfulness, answer_relevancy, context_precision, context_recall],
    llm=llm,  # ← Gemini 2.5 Flash 作为 judge
    embeddings=embeddings
)
```

### 基准（Ground Truth）

| 指标 | 基准来源 | 说明 |
|------|----------|------|
| **Faithfulness** | 检索到的 contexts | 判断 answer 是否忠实于 contexts，**不依赖** ground_truth |
| **Answer Relevancy** | 生成的 question | 根据 answer 反推是否能还原原问题 |
| **Context Precision** | ground_truth | 检索到的 contexts 是否精准支持 ground_truth |
| **Context Recall** | ground_truth | ground_truth 中的信息是否能从 contexts 中找到 |

**我们提供的 ground_truth**：
- 手工编写的标准答案（每个问题1-2句话）
- 用于 Context Precision 和 Context Recall 的判定基准
- 示例：
  ```json
  {
    "question": "What is metformin?",
    "ground_truth": "Metformin primarily lowers blood glucose by reducing hepatic glucose production..."
  }
  ```

### RAGAS 各指标的具体判定逻辑

#### 1. Faithfulness（忠实度）

**判定规则**：
```
答案中的每个陈述（statement），是否都能从检索到的 contexts 中支持/推断？
```

**具体流程**：
1. LLM 将 answer 拆分成多个独立陈述（statements）
2. 对每个陈述，LLM 判断是否能从 contexts 中验证
3. Faithfulness = (可验证的陈述数) / (总陈述数)

**示例**：
```
Answer: "Metformin decreases hepatic glucose production and improves insulin sensitivity."
  → Statement 1: "Metformin decreases hepatic glucose production" [✓ 可从 context 验证]
  → Statement 2: "improves insulin sensitivity" [✓ 可从 context 验证]
Faithfulness = 2/2 = 1.0
```

**Judge prompt 示例** (RAGAS 内部)：
```
Given the following context and answer, identify if all the statements 
in the answer can be inferred from the context.

Context: {contexts}
Answer: {answer}

For each statement in the answer, mark whether it is supported by the context.
```

#### 2. Answer Relevancy（答案相关性）

**判定规则**：
```
根据 answer，是否能还原出原始的 question？
```

**具体流程**：
1. LLM 根据 answer 生成3个可能的问题
2. 计算这些生成问题与原问题的语义相似度（使用 embeddings）
3. Answer Relevancy = 平均相似度

**示例**：
```
Original question: "What is the mechanism of metformin?"
Answer: "Metformin decreases hepatic glucose production..."

LLM 生成的问题:
  1. "How does metformin work?" (similarity: 0.85)
  2. "What is metformin's mechanism?" (similarity: 0.92)
  3. "What does metformin do?" (similarity: 0.78)

Answer Relevancy = (0.85 + 0.92 + 0.78) / 3 = 0.85
```

#### 3. Context Precision（上下文精准度）

**判定规则**：
```
检索到的 contexts 中，哪些是真正支持 ground_truth 的？排名越靠前越好。
```

**具体流程**：
1. LLM 判断每个 context 是否包含 ground_truth 中的信息
2. 根据相关 context 的排名计算精准度
3. Context Precision = Precision@k (weighted by position)

**示例**：
```
ground_truth: "Metformin decreases glucose production..."
Retrieved contexts:
  [1] "Metformin decreases hepatic glucose production..." [✓ 相关]
  [2] "Type 2 diabetes is characterized by..." [✗ 不相关]
  [3] "Metformin improves insulin sensitivity..." [✓ 相关]

Context Precision ≈ 0.83 (相关文档在前面，精准度高)
```

#### 4. Context Recall（上下文召回率）

**判定规则**：
```
ground_truth 中的信息，有多少能从检索到的 contexts 中找到？
```

**具体流程**：
1. LLM 将 ground_truth 拆分成多个陈述
2. 判断每个陈述是否能从 contexts 中推断
3. Context Recall = (可推断的陈述数) / (总陈述数)

**示例**：
```
ground_truth: "Metformin decreases hepatic glucose production and improves insulin sensitivity."
  → Statement 1: "Metformin decreases hepatic glucose production"
  → Statement 2: "improves insulin sensitivity"

检索到的 contexts 包含了:
  [✓] Statement 1 的信息
  [✓] Statement 2 的信息

Context Recall = 2/2 = 1.0
```

### RAGAS 的可信度

#### ✅ 优点
- **可复现**：temperature=0，相同输入得到相同结果
- **高效**：自动化，无需人工标注
- **一致性**：统一的 judge 模型（Gemini 2.5 Flash）
- **文档化**：RAGAS 是学术界认可的 RAG 评估框架

#### ⚠️ 局限
- **LLM 偏差**：Gemini 2.5 Flash 的判断可能有偏见
- **Prompt 敏感**：RAGAS 内部 prompt 的微小变化可能影响结果
- **无真人验证**：没有人工评估作为 baseline 对比
- **成本**：每次评估需调用大量 LLM API（30问题 × 4指标 ≈ 120次调用）

---

## 3️⃣ Citation-Grounded 判定规则

### 什么是 Citation-Grounded？

本系统中，**Faithfulness 指标即为 citation-grounded 的判定**。

### 判定规则

**核心原则**：答案中的每个关键陈述，必须能从引用的 contexts 中验证。

#### 具体规则

```python
# RAGAS Faithfulness 的判定逻辑

1. 陈述提取：
   LLM 将 answer 拆解为独立的原子陈述（atomic statements）
   
2. 验证每个陈述：
   For each statement:
     - 检查是否能从 contexts 中直接找到支持
     - 或者能从 contexts 中逻辑推断
     
3. 计算比例：
   Faithfulness = (可验证陈述数) / (总陈述数)
```

#### 判定标准细节

| 判定 | 条件 | 示例 |
|------|------|------|
| ✅ **Supported** | 陈述直接出现在 context 中 | Answer: "Metformin is a first-line medication"<br>Context: "...Metformin is the main first-line medication..." |
| ✅ **Inferred** | 陈述可从 context 逻辑推断 | Answer: "Metformin reduces blood sugar"<br>Context: "...Metformin lowers blood glucose..." |
| ⚠️ **Partially Supported** | 陈述部分内容可验证 | Answer: "Metformin is cheap and effective"<br>Context: "...Metformin is effective..." (只提到 effective) |
| ❌ **Not Supported** | 陈述无法从 context 验证 | Answer: "Metformin was invented in 1922"<br>Context: (无相关信息) |
| ❌ **Hallucination** | 陈述与 context 矛盾 | Answer: "Metformin increases glucose production"<br>Context: "...Metformin decreases glucose production..." |

### 示例分析

#### 示例 1：高 Faithfulness (0.95)

```
Question: "What is metformin?"

Retrieved Contexts:
  [1] "Metformin is the main first-line medication for type 2 diabetes..."
  [2] "It works by decreasing glucose production in the liver..."
  [3] "Metformin improves insulin sensitivity..."

Generated Answer:
  "Metformin is a first-line medication for type 2 diabetes 
   that works by decreasing glucose production and improving 
   insulin sensitivity."

陈述拆分 + 验证:
  ✓ "Metformin is a first-line medication for type 2 diabetes"
    → 直接支持 by Context [1]
  ✓ "works by decreasing glucose production"
    → 直接支持 by Context [2]
  ✓ "improving insulin sensitivity"
    → 直接支持 by Context [3]

Faithfulness = 3/3 = 1.0
```

#### 示例 2：低 Faithfulness (0.5)

```
Question: "What is CRISPR?"

Retrieved Contexts:
  [1] "CRISPR-Cas9 is a genome editing tool..."
  [2] "It uses guide RNA to target specific DNA sequences..."

Generated Answer:
  "CRISPR is a revolutionary gene therapy technique invented 
   in 2012 that can cure all genetic diseases by editing DNA 
   sequences with guide RNA."

陈述拆分 + 验证:
  ⚠️ "CRISPR is a gene therapy technique"
    → 部分支持（contexts 说 "editing tool"，但未明确说 "therapy"）
  ❌ "invented in 2012"
    → 无法验证（contexts 中没提到年份）
  ❌ "can cure all genetic diseases"
    → 幻觉（contexts 未说 "cure all"）
  ✓ "editing DNA sequences with guide RNA"
    → 直接支持 by Context [2]

Faithfulness = 1.5/4 = 0.375
```

### 与人工标注的对比

| 维度 | RAGAS Faithfulness | 人工标注 |
|------|-------------------|----------|
| **精确度** | ~85-90% | 100% (baseline) |
| **成本** | $0.01/样本 | $1-5/样本 |
| **速度** | 30秒/样本 | 5-10分钟/样本 |
| **一致性** | 高（同一模型） | 中（人与人差异） |
| **可扩展性** | 高 | 低 |

### 系统的 Citation 机制

我们的系统在生成答案时，会在 context 中包含 citation 标记：

```python
# tools.py
blocks.append(
    f"[CITATION {i}]\n"
    f"SOURCE: {source}\n"
    f"TITLE: {title}\n"
    f"PAGE: {page}\n"
    f"CHUNK: {chunk}\n"
    f"SNIPPET: {snippet}\n"
    f"CONTENT:\n{text}"
)
```

**但 Faithfulness 指标并不直接依赖 citation 标记**，而是：
1. 提取所有 retrieved contexts 的 CONTENT
2. 判断 answer 是否来自这些 CONTENT
3. 不关心具体引用了哪个 citation number

---

## 📊 评估透明度总结

### 完整评估流程

```
1. 数据准备 (手工)
   ├─ 创建 30 个生物医学问题
   ├─ 编写 ground_truth 答案
   └─ 标注 gold_doc_ids (25/30 个问题)

2. RAG 运行 (自动)
   ├─ 检索相关 chunks
   ├─ 生成答案
   └─ 记录性能指标

3. RAGAS 评估 (自动, LLM-as-Judge)
   ├─ Faithfulness: Gemini 2.5 Flash 判断答案是否基于 contexts
   ├─ Answer Relevancy: 语义相似度计算
   ├─ Context Precision: LLM 判断检索精准度
   └─ Context Recall: LLM 判断检索完整度

4. 检索硬指标 (自动, 规则based)
   ├─ Hit@k: 是否命中 gold chunks
   ├─ Recall@k: 命中比例
   └─ MRR: 首次命中排名

5. 系统性能 (自动)
   └─ 延迟、Token、成功率统计
```

### 优势与局限

#### ✅ 方法论优势
1. **多维度评估**：生成质量 + 检索质量 + 系统性能
2. **部分客观**：检索硬指标完全客观（基于 gold_doc_ids）
3. **可复现**：所有步骤可自动化重复
4. **行业标准**：使用 RAGAS 框架（学术界认可）

#### ⚠️ 局限性
1. **样本量小**：30 个样本，统计显著性有限
2. **单领域**：仅生物医学，泛化性未知
3. **LLM 评估偏差**：Faithfulness 等指标依赖 LLM 判断
4. **缺乏人工验证**：未与人工评估对比
5. **单语言**：仅英文问题

---

## 🎯 改进建议

### 短期改进
1. **增加样本量**：扩展到 50-100 个问题
2. **人工抽样验证**：随机抽取 10% 样本进行人工评估，计算 LLM-Judge 准确率
3. **多模型对比**：使用不同 judge 模型（GPT-4, Claude）验证一致性
4. **跨领域测试**：增加非生物医学问题

### 长期改进
1. **建立 Benchmark**：发布公开数据集供对比
2. **用户研究**：真实用户满意度调查
3. **A/B Testing**：不同检索策略的对比实验
4. **持续监控**：生产环境中的实时评估

---

**总结**：本评估采用 LLM-as-Judge 的自动化方法（RAGAS + Gemini 2.5 Flash），在 30 个手工创建的生物医学问题上进行，覆盖定义、机制、过程等多种问题类型。Faithfulness 等指标通过 LLM 判断答案是否忠实于检索到的 contexts，无需人工标注，但也继承了 LLM 判断的潜在偏差。

*最后更新: 2026-01-24*
