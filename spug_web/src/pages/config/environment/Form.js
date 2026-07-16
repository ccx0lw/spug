/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useState } from 'react';
import { observer } from 'mobx-react';
import { Modal, Form, Input, InputNumber, message, Switch } from 'antd';
import http from 'libs/http';
import store from './store';

export default observer(function () {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);

  function handleSubmit() {
    setLoading(true);
    const formData = form.getFieldsValue();
    formData['id'] = store.record.id;
    http.post('/api/config/environment/', formData)
      .then(res => {
        message.success('操作成功');
        store.formVisible = false;
        store.fetchRecords()
      }, () => setLoading(false))
  }

  return (
    <Modal
      visible
      maskClosable={false}
      title={store.record.id ? '编辑环境' : '新建环境'}
      onCancel={() => store.formVisible = false}
      confirmLoading={loading}
      onOk={handleSubmit}>
      <Form
        form={form}
        initialValues={{conc_num: 5, deploy_retry_hours: 24, ...store.record}}
        labelCol={{span: 6}}
        wrapperCol={{span: 14}}>
        <Form.Item required name="name" label="环境名称">
          <Input placeholder="请输入环境名称，例如：开发环境"/>
        </Form.Item>
        <Form.Item
          required
          name="key"
          label="唯一标识符"
          tooltip="环境的唯一标识符，会在配置中心API中使用，具体请参考官方文档。"
          extra="可以由字母、数字和下划线组成。">
          <Input placeholder="请输入唯一标识符，例如：dev"/>
        </Form.Item>
        <Form.Item
          required
          name="prod"
          label="是否生产"
          tooltip="环境是否是生产环境，生产环境只能发布标签(tag)的代码"
          extra="生产环境只能发布标签(tag)的代码"
          >
          <Switch defaultChecked={store.record.prod}></Switch>
        </Form.Item>
        <Form.Item
          required
          name="conc_num"
          label="同时发布数量"
          tooltip="同环境下最大同时发布应用数量"
          extra="同环境下最大同时发布应用数量, <= 0 表示不限制"
          >
            <Input placeholder="请输入数量"/>
        </Form.Item>
        <Form.Item
          required
          name="deploy_retry_hours"
          label="失败重试有效期"
          tooltip="发布失败后允许再次发布的时间窗口"
          extra="单位：小时；0 表示禁止失败重试">
          <InputNumber min={0} precision={0} style={{width: '100%'}}/>
        </Form.Item>
        <Form.Item name="desc" label="备注信息">
          <Input.TextArea placeholder="请输入备注信息"/>
        </Form.Item>
      </Form>
    </Modal>
  )
})
