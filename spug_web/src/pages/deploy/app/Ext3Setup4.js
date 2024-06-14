/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useState } from 'react';
import { observer } from 'mobx-react';
import { Form, Button, Input, Row, Col, message } from 'antd';
import { ACEditor } from 'components';
import { http, cleanCommand } from 'libs';
import Tips from './Tips';
import store from './store';

export default observer(function () {
  const [loading, setLoading] = useState(false);

  function handleSubmit() {
    const {dst_dir, dst_repo} = store.deploy;
    const t_dst_dir = dst_dir?.replace(/\/*$/, '/');
    const t_dst_repo = dst_repo?.replace(/\/*$/, '/');
    if (t_dst_repo?.includes(t_dst_dir)) {
      return message.error('存储路径不能位于部署路径内')
    }
    setLoading(true);
    const info = store.deploy;
    info['app_id'] = store.app_id;
    info['extend'] = '3';
    http.post('/api/app/deploy/', info)
      .then(() => {
        message.success('保存成功');
        store.loadDeploys(store.app_id);
        store.ext3Visible = false
      }, () => setLoading(false))
  }

  const info = store.deploy;
  return (
    <Form layout="vertical" style={{padding: '0 120px'}}>
      <Form.Item
        label="应用发布前执行"
        tooltip="在发布的目标主机上运行，当前目录为目标主机上待发布的源代码目录，可执行任意自定义命令。"
        extra={<span>{Tips}，此时还未进行文件变更，可进行一些发布前置操作。</span>}>
        <ACEditor
          readOnly={store.isReadOnly}
          mode="sh"
          theme="tomorrow"
          width="100%"
          height="150px"
          placeholder="输入要执行的命令"
          value={info['hook_pre_host']}
          onChange={v => info['hook_pre_host'] = cleanCommand(v)}
          style={{border: '1px solid #e8e8e8'}}/>
      </Form.Item>
      <Form.Item
        label="应用发布后执行"
        style={{marginTop: 12, marginBottom: 24}}
        tooltip="在发布的目标主机上运行，当前目录为已发布的应用目录，可执行任意自定义命令。"
        extra={<span>{Tips}，可以在发布后进行重启服务等操作。</span>}>
        <ACEditor
          readOnly={store.isReadOnly}
          mode="sh"
          theme="tomorrow"
          width="100%"
          height="150px"
          placeholder="输入要执行的命令"
          value={info['hook_post_host']}
          onChange={v => info['hook_post_host'] = cleanCommand(v)}
          style={{border: '1px solid #e8e8e8'}}/>
      </Form.Item>
      <Form.Item wrapperCol={{span: 14, offset: 6}}>
        <Button disabled={store.isReadOnly} loading={loading} type="primary" onClick={handleSubmit}>提交</Button>
        <Button style={{marginLeft: 20}} onClick={() => store.page -= 1}>上一步</Button>
      </Form.Item>
    </Form>
  )
})