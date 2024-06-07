/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useState } from 'react';
import { observer } from 'mobx-react';
import { Modal, Form, Input, message, Select, Switch } from 'antd';
import http from 'libs/http';
import store from './store';
const { Option } = Select;

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
      <Form form={form} initialValues={store.record} labelCol={{span: 6}} wrapperCol={{span: 14}}>
        <Form.Item
          required
          name="type"
          label="环境类型"
          tooltip="前端/后台发布/镜像编译/其它"
          extra="0:其它 1:前端发布 2:后台发布 3:镜像编译"
          >
          <Select>
            <Option value={0}>其它</Option>
            <Option value={1}>前端发布</Option>
            <Option value={2}>后台发布</Option>
            <Option value={3}>镜像编译</Option>
          </Select>
        </Form.Item>
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
        <Form.Item name="desc" label="备注信息">
          <Input.TextArea placeholder="请输入备注信息"/>
        </Form.Item>
      </Form>
    </Modal>
  )
})