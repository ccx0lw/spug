/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useState, useEffect } from 'react';
import { observer } from 'mobx-react';
import { EditOutlined, DeleteOutlined } from '@ant-design/icons';
import { Modal, Form, Input, Select, Button, Table, Tooltip, message } from 'antd';
import { ACEditor } from 'components';
import Parameter from './Parameter';
import { http, cleanCommand } from 'libs';
import lds from 'lodash';
import S from './store';
import envStore from 'pages/config/environment/store';

export default observer(function () {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const [body, setBody] = useState(S.record.body);
  const [parameter, setParameter] = useState();
  const [parameters, setParameters] = useState([]);
  const [envs, setEnvs] = useState([]);

  function updateEnvs(type) {
    const ids = S.records.filter(x => x.type == (type || S.record.type)).map(x => x.env_id);
    setEnvs(ids)
  }

  useEffect(() => {
    setParameters(S.record.parameters)
    updateEnvs()
    if (envStore.records.length === 0) envStore.fetchRecords()
  }, [])

  function handleSubmit() {
    setLoading(true);
    const formData = form.getFieldsValue();
    formData['id'] = S.record.id;
    formData['body'] = cleanCommand(body);
    formData['parameters'] = parameters;
    http.post('/api/config/file/template/', formData)
      .then(res => {
        message.success('操作成功');
        S.formVisible = false;
        S.fetchRecords()
      }, () => setLoading(false))
  }

  function updateParameter(data) {
    if (data.id) {
      const index = lds.findIndex(parameters, {id: data.id})
      parameters[index] = data
    } else {
      data.id = parameters.length + 1
      parameters.push(data)
    }
    setParameters([...parameters])
    setParameter(null)
  }

  function delParameter(index) {
    parameters.splice(index, 1)
    setParameters([...parameters])
  }

  const info = S.record;
  return (
    <Modal
      visible
      width={800}
      maskClosable={false}
      title={S.record.id ? '编辑模板' : '新建模板'}
      onCancel={() => S.formVisible = false}
      confirmLoading={loading}
      onOk={handleSubmit}>
      <Form form={form} initialValues={info} layout="vertical" style={{padding: '0 20px'}}>
        <Form.Item required label="模板类型" style={{marginBottom: 0}}>
          <Form.Item name="type" style={{display: 'inline-block', width: 'calc(45%)', marginRight: 8}}>
            <Select placeholder="请选择模板类型" onChange={value => updateEnvs(value)}>
              {S.FileTypes.map(item => (
                <Select.Option value={item.value} key={item.key}>{item.key}</Select.Option>
              ))}
            </Select>
          </Form.Item>
        </Form.Item>
        <Form.Item required label="环境" style={{marginBottom: 0}}>
          <Form.Item required name="env_id" style={{display: 'inline-block', width: 'calc(45%)', marginRight: 8}}>
            <Select
              placeholder="请选择环境">
              {envStore.records.map(item => (
                <Select.Option disabled={envs.includes(item.id)} key={item.id} value={item.id}>{item.name}</Select.Option>
              ))}
            </Select>
          </Form.Item>
        </Form.Item>
        <Form.Item required label="模板内容" shouldUpdate={(p, c) => p.interpreter !== c.interpreter} style={{display: 'inline-block', width: 'calc(100%)', marginRight: 8}}>
          {({getFieldValue}) => (
            <ACEditor
              style={{display: 'inline-block', width: 'calc(100%)', marginRight: 8}}
              mode={getFieldValue('type')}
              value={body}
              onChange={val => setBody(val)}
              height="300px"/>
          )}
        </Form.Item>
        <Form.Item label="参数化">
          {parameters.length > 0 && (
            <Table pagination={false} bordered rowKey="id" size="small" dataSource={parameters}>
              <Table.Column title="参数名" dataIndex="name"
                            render={(_, row) => <Tooltip title={row.desc}>{row.name}</Tooltip>}/>
              <Table.Column title="变量名" dataIndex="variable"/>
              <Table.Column title="操作" width={90} render={(item, _, index) => [
                <Button key="1" type="link" icon={<EditOutlined/>} onClick={() => setParameter(item)}/>,
                <Button danger key="2" type="link" icon={<DeleteOutlined/>} onClick={() => delParameter(index)}/>
              ]}>
              </Table.Column>
            </Table>
          )}
          <Button type="link" style={{padding: 0}} onClick={() => setParameter({})}>添加参数</Button>
        </Form.Item>
        <Form.Item name="desc" label="备注信息">
          <Input.TextArea placeholder="请输入模板备注信息"/>
        </Form.Item>
      </Form>
      {parameter ? (
        <Parameter
          parameter={parameter}
          parameters={parameters}
          onCancel={() => setParameter(null)}
          onOk={updateParameter}/>
      ) : null}
    </Modal>
  )
})