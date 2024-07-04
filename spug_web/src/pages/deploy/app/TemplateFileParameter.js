/**
 * Copyright: (c) ccx0lw. https://github.com/ccx0lw/spug
 * Copyright: (c) <fcjava@163.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { Input, Select, Form } from 'antd';
import { isEmpty } from 'lodash';
import Console from '../repository/Console';


function Render({ type, value, onChange, options }) {
  // 根据类型渲染不同的输入组件
  switch (type) {
    case 'string':
      return <Input value={value} onChange={e => onChange(e.target.value)} placeholder="请输入" />;
    case 'password':
      return <Input.Password value={value} onChange={e => onChange(e.target.value)} placeholder="请输入" />;
    case 'select':
      const selectOptions = options.split('\n').map(x => x.split(':'));
      return (
        <Select value={value} onChange={value => onChange(value)} placeholder="请选择">
          {selectOptions.map((item, index) => (
            <Select.Option key={index} value={item[0]}>{item[1] || item[0]}</Select.Option>
          ))}
        </Select>
      );
    case 'textarea':
      return <Input.TextArea value={value} onChange={e => onChange(e.target.value)} placeholder="请输入" />;
    default:
      return null;
  }
}

export default function Parameter({ parameters, param_values, onUpdate }) {
  // 将 param_values 数组转换为对象，以便更容易地通过变量名访问值
  const valuesObj = Array.isArray(param_values) ? param_values.reduce((obj, item) => {
    const key = Object.keys(item)[0]; // 获取当前项的键（变量名）
    obj[key] = item[key]; // 设置对象的键值对
    return obj;
  }, {}) : {};

  return (
    <div>
      {parameters.length === 0 ? <span style={{ display: 'block', textAlign: 'center' }}>无</span> : null}
      {parameters.map(item => {
        let value = valuesObj[item.variable];

        // 从 valuesObj 中获取当前项的值，如果不存在则使用默认值
        if (value === undefined) {
          value = item.default;
          onUpdate(item.variable, item.default)
        }
        
        
        return (
          <Form.Item
            required={item.required}
            key={item.variable}
            name={item.variable}
            label={item.name}
            tooltip={item.desc}
            initialValue={value}
          >
            <Render
              type={item.type}
              options={item.options}
              value={value}
              onChange={value => onUpdate(item.variable, value)}
            />
          </Form.Item>
        );
      })}
    </div>
  );
}
