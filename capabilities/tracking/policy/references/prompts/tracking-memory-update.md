你要根据当前目标 crop、当前场景帧和已有 tracking memory 更新 tracking memory。当前 tracking memory(JSON)：
{current_memory}

本轮成功确认理由：
{confirmation_reason}

本轮候选核验记录(JSON)：
{candidate_checks}

只返回 JSON，不要解释。字段固定为 core、front_view、back_view、distinguish、reference_view。

目标：
- 保留原有 memory 中仍然可信且可迁移的身份信息。
- 吸收这轮新确认到的稳定身份正证据，让 memory 更细、更稳，而不是更短。

更新规则：
1. core：补充这轮新确认到的稳定身份特征；没有更强证据就保留已有内容，不要缩短。
2. front_view：只有当前清楚看到正面时才更新；否则保留已有 front_view。写法仍然要按从上到下连续描述可见的稳定细节。
3. back_view：只有当前清楚看到背面时才更新；否则保留已有 back_view。写法仍然要按从上到下连续描述可见的稳定细节。
4. distinguish：如果这轮确实出现了周边最像目标、后续最容易混淆的人，就按“相似人A：两者都……；A 的……；目标的……；可以通过……明显区分”重写；否则保留空字符串或已有有效内容。不要写“目标区别：……”，不要沿用旧场景描述。
5. reference_view：当前 crop 适合作为稳定正面参考就写 front，适合作为稳定背面参考就写 back；证据不足就写 unknown。只能填写 front、back 或 unknown。

硬规则：
1. 只吸收 confirmation_reason 和 candidate_checks 里真正稳定、可迁移、当前可见的身份正证据。
2. memory 是身份画像，不是当前帧记录。
3. distinguish 只写和周边最像的人如何区分，且只能使用稳定外观差异，不能用位置、动作、姿态、手势、步态、朝向。
4. 位置、动作、姿态、手势、步态、朝向、bbox、轨迹 ID、确认状态都不能进入任何字段。
5. 当前看不清的特征不是反证；没有新证据时保留旧 memory，不要乱改。
6. 不要只写黑上衣、白鞋这种粗描述，要尽量把版型、层次、logo、长度、裤脚、鞋底、材质感、配饰等稳定细节写全。
