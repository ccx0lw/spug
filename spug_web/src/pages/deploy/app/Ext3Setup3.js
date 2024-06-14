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
  function handleNext() {
    store.page += 1
  }

  const info = store.deploy;
  return (
    <Form layout="vertical" style={{padding: '0 120px'}}>
      <Form.Item required label="部署路径" tooltip="应用最终在主机上的部署路径，为了数据安全请确保该目录不存在，Spug 将会自动创建并接管该目录，可使用全局变量，例如：/www/$SPUG_APP_KEY">
        <Input value={info['dst_dir']} onChange={e => info['dst_dir'] = e.target.value} placeholder="请输入部署目标路径"/>
      </Form.Item>
      <Button>Dockerfile</Button>
      <Row gutter={24}>
        <Col span={14}>
          <Form.Item required label="存储路径" tooltip="此目录用于存储应用的历史版本，可使用全局变量，例如：/data/repos/$SPUG_APP_KEY">
            <Input value={info['dst_repo']} onChange={e => info['dst_repo'] = e.target.value} placeholder="请输入部署目标路径"/>
          </Form.Item>
        </Col>
        <Col span={10}>
          <Form.Item required label="版本数量" tooltip="早于指定数量的构建纪录及历史版本会被删除，以释放磁盘空间。">
            <Input value={info['versions']} onChange={e => info['versions'] = e.target.value} placeholder="请输入保存的版本数量"/>
          </Form.Item>
        </Col>
        <Col span={10}>
          <Form.Item required label="镜像名称" tooltip="">
            <Input />
          </Form.Item>
        </Col>
      </Row>
      <Form.Item
        label="编译镜像前执行"
        tooltip="在发布的目标主机上运行，当前目录为目标主机上待发布的源代码目录，可执行任意自定义命令。（eg: 编译本地镜像）"
        extra={<span>{Tips}，此时还未进行文件变更，可进行一些发布前置操作。</span>}>
        <ACEditor
          readOnly={store.isReadOnly}
          mode="sh"
          theme="tomorrow"
          width="100%"
          height="150px"
          placeholder="输入要执行的命令"
          value={info['hook_pre_image']}
          onChange={v => info['hook_pre_image'] = cleanCommand(v)}
          style={{border: '1px solid #e8e8e8'}}/>
      </Form.Item>
      <Form.Item
        label="编译镜像后执行"
        style={{marginTop: 12, marginBottom: 24}}
        tooltip="在发布的目标主机上运行，当前目录为已发布的应用目录，可执行任意自定义命令。（eg: 上传镜像）"
        extra={<span>{Tips}，可以在发布后进行重启服务等操作。</span>}>
        <ACEditor
          readOnly={store.isReadOnly}
          mode="sh"
          theme="tomorrow"
          width="100%"
          height="150px"
          placeholder="输入要执行的命令"
          value={info['hook_post_image']}
          onChange={v => info['hook_post_image'] = cleanCommand(v)}
          style={{border: '1px solid #e8e8e8'}}/>
      </Form.Item>
      <Form.Item wrapperCol={{span: 14, offset: 6}}>
        <Button type="primary" onClick={handleNext}>下一步</Button>
        <Button style={{marginLeft: 20}} onClick={() => store.page -= 1}>上一步</Button>
      </Form.Item>
    </Form>
  )
})