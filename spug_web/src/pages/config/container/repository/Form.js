/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useState, useEffect } from 'react';
import { observer } from 'mobx-react';
import { Modal, Form, Input, message, Select } from 'antd';
import http from 'libs/http';
import store from './store';
import envStore from 'pages/config/environment/store';

export default observer(function () {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false)
  const [envs, setEnvs] = useState([]);

  function updateEnvs() {
    const ids = store.records.map(x => x.env_id);
    setEnvs(ids)
  }

  useEffect(() => {
    if (envStore.records.length === 0) envStore.fetchRecords()
    updateEnvs()
  }, [])

  function handleSubmit() {
    setLoading(true);
    const formData = form.getFieldsValue();
    formData['id'] = store.record.id;
    http.post('/api/config/container/repository/', formData)
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
      title={store.record.id ? '编辑标签' : '新建标签'}
      onCancel={() => store.formVisible = false}
      confirmLoading={loading}
      onOk={handleSubmit}>
      <Form form={form} initialValues={store.record} labelCol={{span: 6}} wrapperCol={{span: 14}}>
        <Form.Item required label="环境" style={{marginBottom: 0}}>
          <Form.Item required name="env_id" style={{display: 'inline-block', width: 'calc(75%)', marginRight: 8}}>
            <Select
              placeholder="请选择环境">
              {envStore.records.map(item => (
                <Select.Option disabled={envs.includes(item.id)} key={item.id} value={item.id}>{item.name}</Select.Option>
              ))}
            </Select>
          </Form.Item>
        </Form.Item>
        <Form.Item 
          required 
          name="repository" 
          label="仓库地址"
          tooltip="eg: 	registry.cn-shenzhen.aliyuncs.com"
          extra="eg: registry.cn-shenzhen.aliyuncs.com">
          <Input placeholder="请输入仓库地址"/>
        </Form.Item>
        <Form.Item
          name="repository_name_prefix"
          label="镜像前缀"
          tooltip="允许为空"
          extra="eg: registry.cn-shenzhen.aliyuncs.com/xxxx/xyz/abc:tag 中的 xxxx/xyz 就是镜像的前缀">
          <Input placeholder="请输入镜像前缀"/>
        </Form.Item>
        <Form.Item name="desc" label="备注信息">
          <Input.TextArea placeholder="请输入备注信息"/>
        </Form.Item>
      </Form>
    </Modal>
  )
})